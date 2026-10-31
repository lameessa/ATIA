"""Dynamic function-calling loop, bounded before every potentially paid request."""
from datetime import datetime,timedelta,timezone
import json
import os
import re
import math
import time
import uuid
import copy
from atia.models import utc_now
from .contracts import Limits,PRICES,SYSTEM,VERSION,DECISION
from .storage import AgentStore,encode,digest
from .tools import AgentTools,TOOLS,context,fingerprint


def validate(value,schema):
    """Validate the small JSON-schema subset used by our closed tool contracts."""
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:validate(value,choice);return
            except ValueError:pass
        raise ValueError('Value does not match the response contract')
    kind=schema['type'];kinds=kind if isinstance(kind,list) else [kind]
    matches={'null':value is None,'string':isinstance(value,str),'object':isinstance(value,dict),'array':isinstance(value,list),
             'integer':isinstance(value,int) and not isinstance(value,bool),'number':isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)}
    if not any(matches.get(k,False) for k in kinds):raise ValueError('Invalid JSON value type')
    if 'enum' in schema and value not in schema['enum']:raise ValueError('Invalid enum value')
    if isinstance(value,dict):
        if set(value)!=set(schema['properties']):raise ValueError('Missing or unexpected JSON fields')
        for k,v in value.items():validate(v,schema['properties'][k])
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0):raise ValueError('Too few array items')
        for item in value:validate(item,schema['items'])
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if value<schema.get('minimum',value) or value>schema.get('maximum',value):raise ValueError('Numeric value outside contract bounds')


def validate_claims(decision,tools):
    from atia.moderation.policy import clean_evidence
    if not clean_evidence(tools.memory.db,decision):raise ValueError('Unapproved/removed photo evidence is forbidden in decisions and proposals')
    if not decision['explanation'].strip():raise ValueError('Decision explanation is empty')
    for claim in decision['claims']:
        if not claim['claim'].strip():raise ValueError('Claim is empty')
        tools.validate_refs(claim['evidence_refs'])
        # A valid reference ID alone cannot support an ungrounded popularity or
        # promotional-gap assertion. Catch these observed high-risk overclaims;
        # this is deliberately not advertised as a general entailment checker.
        claim_text=claim['claim'].casefold()
        evidence_text=encode([tools.refs[r] for r in claim['evidence_refs']]).casefold()
        negated=bool(re.search(r'\b(not|cannot|unproven|uncertain|insufficient|no evidence|hypothesis|potential|may|could)\b',claim_text))
        for term in ('popular','underpromoted','high demand','strong demand','hidden gem','overlooked'):
            if not negated and term in claim_text and term not in evidence_text:
                raise ValueError('Unsupported popularity/demand/promotional-gap assertion')
    if not decision['claims']:raise ValueError('Decision must cite inspected evidence')


def guarded_decision(decision,tools):
    validate(decision,DECISION);validate_claims(decision,tools)
    if decision['decision'] in ('CREATE','UPDATE'):
        proposal=decision['proposal'];assessment=tools.data['assessment'] or {}
        if not proposal or not assessment.get('entities') or assessment.get('association_status','').startswith('unresolved'):
            raise ValueError('Marketing proposal lacks a resolved authoritative entity')
        tools.validate_refs(proposal['supporting_evidence'])
        # Provisional photos cannot be used as verified attraction marketing evidence.
        if any(not r.startswith('https://') for r in proposal['supporting_evidence']):
            raise ValueError('Draft opportunity needs returned source URLs, not cluster/popularity evidence alone')
        if not decision['uncertainties']:raise ValueError('Draft must explicitly state uncertainty')
        for field,value in proposal.items():
            if field=='supporting_evidence':continue
            if not all(value[lang].strip() for lang in ('ar','en')):raise ValueError('Bilingual proposal field is empty')
        names=[e['verified_name'].casefold() for e in assessment['entities']]
        if not any(name in proposal['destination']['en'].casefold() for name in names):
            raise ValueError('Proposal destination must be an inspected verified entity')
        if decision['decision']=='UPDATE':
            row=tools.memory.db.execute('SELECT * FROM agent_proposals WHERE proposal_id=? AND cluster_id=?',
                (decision['previous_proposal_id'],tools.cluster_id)).fetchone()
            if row is None:raise ValueError('UPDATE needs an existing proposal for this location')
        elif decision['previous_proposal_id'] is not None:raise ValueError('CREATE must not specify a previous proposal')
    elif decision['proposal'] is not None:raise ValueError('Investigation/no-action cannot create a proposal')
    return decision


def fallback(reason):
    return {'decision':'INVESTIGATE','explanation':reason,'claims':[],'uncertainties':[reason],
            'next_actions':['Review stored evidence and resolve the reported limitation before marketing action.'],
            'previous_proposal_id':None,'proposal':None}


def make_client(limits):
    from openai import OpenAI
    key=os.getenv('OPENAI_API_KEY','').strip()
    if not key:raise ValueError('OPENAI_API_KEY is missing; paste it into the local .env file')
    # Retry manually only when the server explicitly rejected a request with 429.
    # Never silently replay timeouts/5xx requests that may already have been billed.
    return OpenAI(api_key=key,base_url='https://api.openai.com/v1',timeout=limits.timeout_seconds,max_retries=0)


def compact_history(conversation):
    """Lossless removal of repeated referenced payloads, not new LLM summaries."""
    seen=set();result=[]
    def compact(value):
        if isinstance(value,dict):
            ref=value.get('evidence_ref')
            if ref and ref in seen:return {'previously_returned_evidence_ref':ref}
            if ref:seen.add(ref)
            return {k:compact(v) for k,v in value.items()}
        if isinstance(value,list):return [compact(v) for v in value]
        return value
    for item in conversation:
        if item.get('type')=='function_call_output':
            result.append({**item,'output':encode(compact(json.loads(item['output'])))})
        else:result.append(item)
    return result


def run_agent(store,cluster_id=None,goal=None,
              limits=None,client=None,refresh=False,progress=None,provider=None,pause=time.sleep,resume_run_id=None,target_entity_id=None):
    limits=limits or Limits.load();emit=progress or (lambda _:None);started=time.monotonic()
    discovery=cluster_id is None
    if target_entity_id and not discovery:raise ValueError("Selected entity uses the complete discovery/campaign profile, not the legacy cluster agent")
    if discovery:
        from .discovery_contracts import VERSION as version,PROMPT as instructions,DECISION as contract,GOAL
        from .discovery_storage import DiscoveryStore
        from .discovery_tools import DiscoveryTools,TOOLS as tool_definitions,candidate_pool,discovery_fingerprint
        from .campaigns import guarded_discovery_decision as guard,fallback as discovery_fallback,campaign_fingerprint
        if resume_run_id:raise ValueError('Discovery cycles stop at their limit; no automatic paid continuation')
        memory=DiscoveryStore(store);pool=candidate_pool(store)
        if target_entity_id:
            pool=[p for p in pool if any(e['entity_id']==target_entity_id for e in p['candidate_names'])]
            if not pool:raise ValueError('Destination has no verified identity with eligible photographic evidence')
            entity=memory.db.execute("SELECT * FROM verified_location_entities WHERE entity_id=? AND verification_status='authoritative_source_name_confirmed' AND entity_type IN ('destination','attraction')",(target_entity_id,)).fetchone()
            if not entity:raise ValueError('Destination identity is unverified')
            goal='Investigate a justified bilingual campaign for the verified entity '+entity['verified_name']+'. The user selects the entity, not the claims or outcome. INVESTIGATE/NO_ACTION remain valid.'
            instructions+='\nSELECTED-DESTINATION MODE: independently investigate the supplied verified entity; campaign identity must match it. Do not change the destination.\n'
            instructions+='Entity IDs and geographic cluster IDs are different. Use the exact cluster_id returned by list_candidates when calling a tool.\n'
            # Scope strict function arguments to real geographic IDs. The model
            # still chooses tools and outcomes; an entity-ID typo cannot consume
            # the small run repeatedly or silently select another area.
            tool_definitions=copy.deepcopy(tool_definitions)
            for definition in tool_definitions:
                properties=definition['parameters']['properties']
                if 'cluster_id' in properties:properties['cluster_id']={'type':'string','enum':[p['cluster_id'] for p in pool]}
        data={'candidates':pool,'target_entity_id':target_entity_id}
        fingerprint_fn=discovery_fingerprint;tool_class=DiscoveryTools;goal=GOAL if goal is None else goal
    else:
        version=VERSION;instructions=SYSTEM;contract=DECISION;tool_definitions=TOOLS;guard=guarded_decision
        memory=AgentStore(store);data=context(store,cluster_id);fingerprint_fn=fingerprint;tool_class=AgentTools
        goal='Assess whether a tourism marketing draft is justified by available evidence.' if goal is None else goal
    if not isinstance(goal,str) or not goal.strip() or len(goal)>1000:raise ValueError('Goal must contain 1–1000 characters')
    evidence_key=fingerprint_fn(store,data)
    key=digest({'version':version,'target_entity_id':target_entity_id,'cluster':cluster_id,'evidence':evidence_key,'goal':goal,'limits':limits.to_dict()})
    cached=memory.db.execute(f'SELECT * FROM {memory.run_table} WHERE cache_key=? AND status=? ORDER BY completed_at DESC LIMIT 1',(key,'completed')).fetchone()
    if not resume_run_id and not refresh and cached and datetime.fromisoformat(cached['completed_at'])>=datetime.now(timezone.utc)-timedelta(hours=24):
        result=json.loads(cached['result_json'])
        return {**result,'cached':True,'replay_llm_requests':0,'replay_tool_calls':0,'replay_estimated_cost_usd':0,
                'replay_elapsed_seconds':round(time.monotonic()-started,3)}
    empty_discovery=discovery and not data['candidates']
    client=client or (None if empty_discovery else make_client(limits))
    prior_result=None
    if resume_run_id:
        row=memory.db.execute('SELECT * FROM agent_runs WHERE run_id=?',(resume_run_id,)).fetchone()
        if row is None or row['cluster_id']!=cluster_id or row['goal']!=goal or row['limits_json']!=encode(limits.to_dict()):
            raise ValueError('Resume requires the same location, goal and limits')
        prior_result=json.loads(row['result_json']) if row['result_json'] else None
        if row['status']!='needs_review' or not prior_result or prior_result['errors']!=['Input size limit reached; no additional request sent']:
            raise ValueError('Only a context-limited run can resume safely; uncertain API failures cannot be replayed')
        if prior_result['llm_requests']>=limits.max_steps or evidence_key!=prior_result['evidence_fingerprint']:
            raise ValueError('Resume has no remaining requests or evidence changed')
        if limits.model!='gpt-4o-mini':raise ValueError('Resume currently supports the nonreasoning default only')
        run_id=resume_run_id
    else:
        run_id='agent-'+uuid.uuid4().hex
        with memory.db:memory.db.execute(f'INSERT INTO {memory.run_table} VALUES(?,?,?,?,?,?,?,?,?,?)',
            (run_id,cluster_id,goal,utc_now(),None,key,'running',limits.model,encode(limits.to_dict()),None))
    tools=tool_class(store,memory,run_id,cluster_id,data,limits,provider)
    previous=memory.memory(cluster_id)
    previous['runs']=[r for r in previous['runs'] if r['run_id']!=run_id]
    # Memory is retrieved at startup; its statements are interpretations, not facts.
    memory_ref=tools.reference('memory:'+(cluster_id or 'discovery'),previous)
    conversation=[{'role':'user','content':encode({'goal':goal,'selected_cluster_id':cluster_id,
        'prior_memory_available':{'evidence_ref':memory_ref,'run_ids':[r['run_id'] for r in previous['runs']],
                                 'proposal_ids':[p['proposal_id'] for p in previous['proposals']]},
        'limits':{'requests':limits.max_steps,'tool_calls':limits.max_tool_calls,'searches':limits.max_searches}})}]
    decision=None;errors=[];trace=[];requests=0;calls=0;usd=0;usage_totals={'input_tokens':0,'output_tokens':0};model_decision=None
    if empty_discovery:
        decision=discovery_fallback('No eligible approved geographic candidates are available.')
        decision['decision']='NO_ACTION'
        ref=tools.reference('catalogue:empty',{'eligible_areas':0})
        decision['claims']=[{'claim':'No eligible approved geographic candidates are available.','evidence_refs':[ref]}]
    if prior_result:
        tools.refs=prior_result['evidence_registry'];trace=prior_result['trace'];calls=prior_result['tool_calls']
        requests=prior_result['llm_requests'];usd=prior_result['estimated_api_cost_usd'];usage_totals=prior_result['usage']
        tools.searches=prior_result['additional_tavily_searches']
        for call in memory.db.execute('SELECT * FROM agent_tool_calls WHERE run_id=? ORDER BY called_at',(run_id,)):
            conversation.append({'type':'function_call','call_id':call['call_id'],'name':call['name'],'arguments':call['arguments_json']})
            conversation.append({'type':'function_call_output','call_id':call['call_id'],'output':call['result_json']})
        conversation=compact_history(conversation)
    if discovery:
        conversation[0]['content']=encode({'goal':goal,'mode':'autonomous_discovery','eligible_area_count':len(data['candidates']),
            'prior_cycle_ids':[r['run_id'] for r in previous['discovery_cycles']],
            'limits':{'requests':limits.max_steps,'tools':limits.max_tool_calls,'searches':limits.max_searches}})
    schemas={t['name']:t['parameters'] for t in tool_definitions};seen_calls=set();rate_retries=0
    for step in range(requests+1,limits.max_steps+1):
        if decision is not None:break
        available=calls<limits.max_tool_calls and step<limits.max_steps
        kwargs={'model':limits.model,'instructions':instructions,'input':compact_history(conversation),
                'tools':tool_definitions,'parallel_tool_calls':False,'tool_choice':'auto' if available else 'none',
                'max_output_tokens':limits.max_output_tokens,'store':False,
                'text':{'format':{'type':'json_schema','name':'atia_discovery' if discovery else 'atia_decision','strict':True,'schema':contract}}}
        if limits.model=='gpt-5.4-nano':kwargs['reasoning']={'effort':'none'}
        elif limits.model=='gpt-5-mini':kwargs['reasoning']={'effort':'minimal'}
        # UTF-8 bytes + protocol margin upper-bounds text tokens conservatively;
        # no images/audio or opaque previous_response_id state are sent.
        size=len(encode(kwargs).encode())
        if size>limits.max_input_bytes:
            errors.append('Input size limit reached; no additional request sent');break
        prices=PRICES[limits.model]
        reserve=((size+4096)*prices[0]+limits.max_output_tokens*prices[1])/1_000_000
        try:identifier=memory.reserve(run_id,step,reserve,limits)
        except RuntimeError as exc:errors.append(str(exc));break
        emit(f'{cluster_id}: LLM request {step}/{limits.max_steps}; {calls}/{limits.max_tool_calls} tool calls used')
        requests+=1
        try:
            response=client.responses.create(**kwargs)
            usd+=memory.finish_request(identifier,response,prices)
            usage_totals['input_tokens']+=response.usage.input_tokens;usage_totals['output_tokens']+=response.usage.output_tokens
        except Exception as exc:
            # Do not log remote exception bodies, headers or credentials.
            status=getattr(exc,'status_code',None)
            errors.append(f'OpenAI request failed ({type(exc).__name__}, status={status}); reservation retained')
            if status==429 and rate_retries<1 and step<limits.max_steps:
                rate_retries+=1;pause(1);continue
            break
        if response.status!='completed':
            errors.append('OpenAI response was incomplete/refused; no automatic paid repair');break
        # Reasoning protocol items must be forwarded if a configurable reasoning
        # model is selected; private reasoning is not included in local run logs.
        conversation.extend(item.model_dump(exclude_none=True) for item in response.output)
        functions=[item for item in response.output if item.type=='function_call']
        if not functions:
            try:
                proposed=json.loads(response.output_text)
                if isinstance(proposed,dict) and proposed.get('decision') in ('CREATE','UPDATE','INVESTIGATE','NO_ACTION'):model_decision=proposed['decision']
                decision=guard(proposed,tools)
            except (ValueError,TypeError,KeyError) as exc:
                detail=(' ('+str(exc)+')') if discovery and not isinstance(exc,json.JSONDecodeError) else ''
                errors.append('Final decision failed schema/evidence validation; human investigation required'+detail)
            break
        if not available:
            errors.append('Model called tools after the configured limit');break
        for call in functions:
            if calls>=limits.max_tool_calls:errors.append('Tool-call limit reached');break
            calls+=1
            refs_before=dict(tools.refs)
            try:
                if call.call_id in seen_calls:raise ValueError('Repeated tool call ID')
                seen_calls.add(call.call_id)
                args=json.loads(call.arguments)
                if call.name not in schemas:raise ValueError('Unknown tool')
                validate(args,schemas[call.name])
                out=tools.execute(call.name,args)
            except Exception as exc:
                args={};out={'error':'Tool failed safely','error_type':type(exc).__name__,
                             'detail':str(exc) if isinstance(exc,ValueError) else 'Source unavailable or local tool error; inspect independently.'}
            output=encode(out)
            if len(output.encode())>18000:
                # Explicitly indicate omitted data rather than silently cutting JSON.
                tools.refs=refs_before
                out={'error':'Tool result exceeds small-run context limit','hint':'Request a narrower evidence view'};output=encode(out)
            with memory.db:memory.db.execute(f'INSERT OR IGNORE INTO {memory.tool_table} VALUES(?,?,?,?,?,?)',
                (run_id,call.call_id,call.name,call.arguments,output,utc_now()))
            trace.append({'step':step,'tool':call.name,'arguments':args,'status':'error' if 'error' in out else 'ok'})
            emit(f"  tool: {call.name} ({trace[-1]['status']})")
            conversation.append({'type':'function_call_output','call_id':call.call_id,'output':output})
    if decision is None:
        reason='; '.join(errors) or 'Agent step limit reached without a valid grounded final decision'
        decision=discovery_fallback(reason,tools.cluster_id) if discovery else fallback(reason)
    evidence_key=fingerprint_fn(store,data)
    key=digest({'version':version,'target_entity_id':target_entity_id,'cluster':cluster_id,'evidence':evidence_key,'goal':goal,'limits':limits.to_dict()})
    proposal_id=None
    campaign_id=None
    if discovery and decision['decision'] in ('CREATE','UPDATE'):
        material=campaign_fingerprint(tools,decision)
        campaign_id,created=memory.save_campaign(run_id,tools.cluster_id,decision['campaign'],material,
            {'references':tools.refs,'hidden_gem':decision['hidden_gem'],'claims':decision['claims']},decision['previous_campaign_id'])
        if not created:decision.update(decision='NO_ACTION',campaign=None,explanation='Existing campaign reused; no duplicate draft created.')
    elif not discovery and decision['decision'] in ('CREATE','UPDATE'):
        old=memory.db.execute('SELECT proposal_id FROM agent_proposals WHERE cluster_id=? AND evidence_fingerprint=?',(cluster_id,evidence_key)).fetchone()
        if old:
            proposal_id=old['proposal_id'];decision['decision']='NO_ACTION';decision['proposal']=None
            decision['explanation']='A draft already exists for this evidence snapshot; no duplicate proposal created.'
        else:
            proposal_id='proposal-'+uuid.uuid4().hex
            with memory.db:memory.db.execute('INSERT INTO agent_proposals VALUES(?,?,?,?,?,?,?,?)',
                (proposal_id,run_id,cluster_id,utc_now(),'PENDING_APPROVAL',decision['previous_proposal_id'],evidence_key,encode(decision['proposal'])))
    # Include additional Tavily observations in the next-run fingerprint, even
    # when they are not yet incorporated into the authoritative identity layer.
    charged=memory.db.execute(f'SELECT coalesce(sum(charged_usd),0) FROM {memory.request_table} WHERE run_id=?',(run_id,)).fetchone()[0]
    result={'run_id':run_id,'cluster_id':tools.cluster_id,'model':limits.model,'agent_version':version,'cached':False,
        'decision':decision,'proposal_id':proposal_id,'proposal_status':'PENDING_APPROVAL' if proposal_id else None,
        'llm_requests':requests,'tool_calls':calls,'additional_tavily_searches':tools.searches,
        'trace':trace,'evidence_registry':tools.refs,'evidence_fingerprint':evidence_key,
        'usage':usage_totals,'estimated_api_cost_usd':round(usd,8),'conservative_ledger_charge_usd':round(charged,8),
        'elapsed_seconds':round(time.monotonic()-started+(prior_result['elapsed_seconds'] if prior_result else 0),3),'errors':errors,
        'resumed_after_context_guard':bool(prior_result),
        'cost_note':'Token estimate using documented standard rates; cached input not discounted. Uncertain failed requests retain reserved upper bounds. Local ledger is not account-wide billing.'}
    if discovery:
        result.update(mode='autonomous_discovery',eligible_candidate_count=len(data['candidates']),
            model_decision=model_decision,
            candidates_considered=[p for p in data['candidates'] if p['cluster_id'] in tools.considered],
            selected_cluster_id=tools.cluster_id,campaign_id=campaign_id,
            campaign_status='PENDING_APPROVAL' if campaign_id else None,
            tavily_source_observations=tools.source_observations,
            tavily_network_requests=getattr(tools.provider,'network_calls',0),tavily_cache_hits=getattr(tools.provider,'cache_hits',0))
    status='completed' if not errors else 'needs_review'
    with memory.db:
        memory.db.execute(f'UPDATE {memory.run_table} SET completed_at=?,status=?,result_json=?,cache_key=?,cluster_id=? WHERE run_id=?',
            (utc_now(),status,encode(result),key,tools.cluster_id,run_id))
    return result
