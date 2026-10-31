import argparse
import json
import sys
from atia.config import Settings
from atia.collectors.flickr import FlickrError, collect, live_client
from atia.collectors.historical import import_historical
from atia.collectors.regional import collect_regions
from atia.storage.sqlite import PhotoStore


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def main():
    parser = argparse.ArgumentParser(description="ATIA metadata collector")
    parser.add_argument("--db", help="SQLite database path (overrides ATIA_DB_PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("collect", help="Collect new public geotagged Saudi photos")
    live.add_argument("--limit", type=positive, default=50)
    live.add_argument("--max-pages", type=positive, default=16)
    regional = sub.add_parser("collect-regions", help="Collect new Saudi photos with independent regional quotas")
    regional.add_argument("--per-region", type=positive, default=10)
    regional.add_argument("--max-pages", type=positive, default=16)
    regional.add_argument("--region-seconds", type=positive, default=180)
    vision = sub.add_parser("analyze", help="Analyze accessible photos with pretrained OpenCLIP")
    vision.add_argument("--limit", type=positive, default=10)
    vision.add_argument("--max-candidates", type=positive, default=100)
    vision.add_argument("--source", choices=["flickr_live", "afaq_historical"])
    vision.add_argument("--batch-size", type=positive, default=4)
    vision.add_argument("--thresholds", help="JSON threshold configuration (defaults to built-in heuristics)")
    vision.add_argument("--unscreened-dimensions", action="store_true", help="Research-only previous dimensional analysis without relevance gating")
    vision.add_argument("--sample-id", help="Use an existing prepared sample for gated analysis")
    vision.add_argument("--legacy", action="store_true", help="Run the previous single-dimension analysis")
    vision.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    prepare = sub.add_parser("prepare-review", help="Prepare a deterministic regional visual review sample")
    prepare.add_argument("--per-region", type=positive, default=3)
    prepare.add_argument("--seed", default="atia-review-v1")
    prepare.add_argument("--no-audit", action="store_true")
    screen = sub.add_parser("screen", help="Screen a prepared sample before destination analysis")
    screen.add_argument("sample_id")
    screen.add_argument("--batch-size", type=positive, default=4)
    labels = sub.add_parser("import-review-labels", help="Import versioned image-specific review annotations")
    labels.add_argument("sample_id")
    labels.add_argument("path")
    review = sub.add_parser("review-report", help="Export relevance predictions and reviewer labels with previews")
    review.add_argument("sample_id")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--output-dir", default="data/relevance-review")
    sentiment = sub.add_parser("sentiment", help="Collect comments and analyze Arabic/English sentiment")
    sentiment.add_argument("--limit", type=positive, default=10)
    sentiment.add_argument("--batch-size", type=positive, default=16)
    sentiment.add_argument("--historical-path", default="Afaq_RawData.json")
    sentiment.add_argument("--refresh-comments", action="store_true")
    sentiment.add_argument("--destination-map", help="Explicit JSON photo-to-destination mappings")
    destinations = sub.add_parser("destinations", help="Build or inspect geographic destination evidence")
    destination_commands = destinations.add_subparsers(dest="destination_command", required=True)
    build = destination_commands.add_parser("build")
    build.add_argument("--distance-km", type=float, default=1.0)
    build.add_argument("--min-accuracy", type=int, default=12)
    build.add_argument("--places", help="Explicit verified place annotations JSON")
    build.add_argument("--report", default="DESTINATION_INTELLIGENCE.md")
    inspect = destination_commands.add_parser("inspect")
    inspect.add_argument("--run-id")
    inspect.add_argument("--destination-id")
    intelligence = sub.add_parser("intelligence", help="Deterministic Flickr intelligence; no paid services")
    intelligence_commands = intelligence.add_subparsers(dest="intelligence_command", required=True)
    restore = intelligence_commands.add_parser("restore-images", help="Check current Flickr status/licence and cache archive images")
    restore.add_argument("--limit", type=positive)
    restore.add_argument("--refresh", action="store_true", help="Recheck photos that already succeeded")
    intelligence_build = intelligence_commands.add_parser("build", help="Extract themes/places and rebuild opportunity signals")
    intelligence_build.add_argument("--subset-size", type=positive, default=50)
    intelligence_build.add_argument("--report", default="FLICKR_INTELLIGENCE.md")
    intelligence_inspect = intelligence_commands.add_parser("inspect", help="Print the latest signals")
    intelligence_inspect.add_argument("--kind", choices=["named_destination", "regional_experience", "tourism_theme"])
    opportunities = sub.add_parser("opportunities", help="Curated marketing opportunities and campaign drafts")
    opportunity_commands = opportunities.add_subparsers(dest="opportunity_command", required=True)
    opportunity_commands.add_parser("build", help="Create opportunities from the latest intelligence signals")
    find_images = opportunity_commands.add_parser("find-images", help="Free licence-filtered Flickr image search")
    find_images.add_argument("--wanted", type=positive, default=8)
    find_images.add_argument("--opportunity")
    review_image = opportunity_commands.add_parser("review-image", help="Accept or reject one image candidate")
    review_image.add_argument("--opportunity", required=True)
    review_image.add_argument("--photo-id", required=True)
    review_image.add_argument("--decision", choices=["accept", "reject"], required=True)
    review_image.add_argument("--reviewer", required=True)
    review_image.add_argument("--reason", required=True)
    opportunity_commands.add_parser("recover-rejected", help="Save earlier model output that stricter checks refused. No model call")
    opportunity_generate = opportunity_commands.add_parser("generate", help="Investigate one opportunity. Paid unless --dry-run")
    opportunity_generate.add_argument("--opportunity")
    opportunity_generate.add_argument("--dry-run", action="store_true", help="Show the evidence and cost cap; no API call")
    opportunity_generate.add_argument("--confirm-paid", action="store_true", help="Required to make the paid OpenAI request")
    images = sub.add_parser("images", help="Human review before any photograph can be displayed")
    image_commands = images.add_subparsers(dest="image_command", required=True)
    image_queue = image_commands.add_parser("queue", help="List photos that passed automated checks and need a person")
    image_queue.add_argument("--limit", type=positive)
    image_review = image_commands.add_parser("review", help="Record a person's decision on one image")
    image_review.add_argument("--source", choices=["afaq_historical", "flickr_live"], required=True)
    image_review.add_argument("--photo-id", required=True)
    image_review.add_argument("--sha256", required=True, help="The image hash shown by images queue")
    image_review.add_argument("--decision", choices=["approve", "reject", "uncertain"], required=True)
    image_review.add_argument("--reviewer", required=True)
    image_review.add_argument("--reason", required=True)
    image_review.add_argument("--viewed-image", action="store_true")
    image_review.add_argument("--confirm-safe", action="store_true")
    image_review.add_argument("--confirm-licence", action="store_true")
    demo = sub.add_parser("demo", help="Public demo data: no API keys")
    demo_commands = demo.add_subparsers(dest="demo_command", required=True)
    demo_commands.add_parser("init", help="Create data/demo.sqlite3 from demo/seed.json")
    demo_commands.add_parser("validate", help="Run the real validator on the stored draft, with no model call")
    research = sub.add_parser("research", help="Source-grounded promotional coverage research")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    research_run = research_commands.add_parser("run")
    research_run.add_argument("--destination-id", action="append", dest="destination_ids")
    research_run.add_argument("--limit", type=positive, default=5)
    research_run.add_argument("--provider", choices=["brave", "evidence-file", "tavily"], default="tavily")
    research_run.add_argument("--evidence-file")
    research_run.add_argument("--candidates", default="config/location-research-candidates.json", help="Candidate hints, never authoritative evidence")
    research_run.add_argument("--resolutions", help="Source-backed destination identity resolutions JSON")
    research_run.add_argument("--refresh", action="store_true")
    research_run.add_argument("--report", default="PROMOTIONAL_RESEARCH.md")
    research_commands.add_parser("entities", help="Inspect separate geographic clusters, verified entities, parents and unresolved links")
    research_inspect = research_commands.add_parser("inspect")
    research_inspect.add_argument("--destination-id")
    research_inspect.add_argument("--provider", choices=["historical", "tavily"], default="tavily")
    historical = sub.add_parser("import-historical")
    historical.add_argument("path")
    moderation = sub.add_parser("moderation", help="Private quarantine evaluation and explicit human review; never a public gallery")
    moderation_commands = moderation.add_subparsers(dest="moderation_command", required=True)
    moderation_commands.add_parser("evaluate", help="Evaluate ALL live photos locally, without paid APIs or external image uploads")
    moderation_commands.add_parser("status")
    moderation_commands.add_parser("retire", help="Remove only visually confirmed clear rejections, never ambiguous images")
    moderation_labels = moderation_commands.add_parser("import-inspections")
    moderation_labels.add_argument("path")
    moderation_queue = moderation_commands.add_parser("queue")
    moderation_queue.add_argument("--output-dir", default="data/private-review")
    moderation_review = moderation_commands.add_parser("review")
    moderation_review.add_argument("photo_id")
    moderation_review.add_argument("--approve", action="store_true")
    moderation_review.add_argument("--reviewer", required=True)
    moderation_review.add_argument("--reason", required=True)
    moderation_review.add_argument("--confirm", action="store_true")
    agent = sub.add_parser("agent", help="Bounded autonomous evidence investigation; one location per run")
    agent_commands = agent.add_subparsers(dest="agent_command", required=True)
    discover = agent_commands.add_parser("discover", help="Autonomously select a candidate and investigate a hidden-gem campaign opportunity; no destination or prompt required")
    discover.add_argument("--refresh", action="store_true")
    discover.add_argument("--scheduled", action="store_true", help="Declare an external scheduler invocation; does not install a schedule")
    discover.add_argument("--authorize-paid-run", action="store_true", help="Explicit authorization required for externally scheduled runs")
    discovery_inspect = agent_commands.add_parser("discovery-inspect")
    discovery_inspect.add_argument("--run-id")
    campaigns = agent_commands.add_parser("campaigns", help="Inspect full bilingual campaign drafts; never publishes")
    campaigns.add_argument("--cluster-id")
    agent_run = agent_commands.add_parser("run")
    agent_run.add_argument("--cluster-id", required=True)
    agent_run.add_argument("--goal", default="Assess whether a tourism marketing draft is justified by available evidence.")
    agent_run.add_argument("--refresh", action="store_true", help="Bypass completed-decision cache; may incur a new bounded charge")
    agent_run.add_argument("--resume-run-id", help="Resume a context-limited run within its ORIGINAL request budget")
    agent_inspect = agent_commands.add_parser("inspect")
    agent_inspect.add_argument("--run-id")
    proposals = agent_commands.add_parser("proposals")
    proposals.add_argument("--cluster-id", required=True)
    sub.add_parser("stats")
    args = parser.parse_args()
    settings = Settings.load()
    if args.command == "demo":
        from atia.demo import validate_demo
        if args.demo_command == "validate":
            print(json.dumps(validate_demo(), indent=2, ensure_ascii=False))
            return 0
        args.db = args.db or "data/demo.sqlite3"
    try:
        with PhotoStore(args.db or settings.db_path) as store:
            if args.command == "collect":
                result = collect(live_client(settings.api_key), store, args.limit, args.max_pages)
            elif args.command == "collect-regions":
                result = collect_regions(live_client(settings.api_key), store,
                    args.per_region, args.max_pages, args.region_seconds,
                    progress=lambda message: print(message, file=sys.stderr, flush=True))
            elif args.command == "analyze":
                from atia.vision.images import FlickrImageFetcher
                from atia.vision.model import OpenClipAnalyzer
                from atia.vision.pipeline import analyze_batch
                fetcher = FlickrImageFetcher(live_client(settings.api_key))
                progress = lambda message: print(message, file=sys.stderr, flush=True)
                if args.legacy:
                    result = analyze_batch(store, fetcher,
                        lambda: OpenClipAnalyzer(device=args.device), args.limit, args.max_candidates,
                        args.source, progress=progress)
                elif args.unscreened_dimensions:
                    from atia.vision.dimensions import Thresholds
                    from atia.vision.dimensional_model import DimensionalAnalyzer
                    from atia.vision.dimensional_pipeline import analyze_dimensions
                    result = analyze_dimensions(store, fetcher,
                        lambda: DimensionalAnalyzer(device=args.device), args.limit, args.max_candidates,
                        args.batch_size, Thresholds.load(args.thresholds), args.source, progress)
                else:
                    if args.thresholds:
                        raise ValueError("Screened analysis uses the fixed screening policy. --thresholds is for --unscreened-dimensions research mode.")
                    from atia.vision.review_sample import prepare_sample
                    from atia.vision.screen_pipeline import screen_sample
                    from atia.vision.screen_model import ScreeningAnalyzer, model_spec
                    import math
                    sample_id = args.sample_id
                    if sample_id is None:
                        sample = prepare_sample(store, fetcher, math.ceil(args.limit/5),
                            seed="atia-analysis-v1", include_audit=False, progress=progress, source=args.source)
                        sample_id = sample["sample_id"]
                    spec = model_spec()
                    if args.device != "cpu":
                        spec["device"] = args.device
                    result = screen_sample(store, sample_id, args.batch_size,
                        analyzer_factory=lambda: ScreeningAnalyzer(device=args.device),
                        progress=progress, spec=spec, limit=args.limit)

            elif args.command == "prepare-review":
                from atia.vision.images import FlickrImageFetcher
                from atia.vision.review_sample import prepare_sample
                result = prepare_sample(store, FlickrImageFetcher(live_client(settings.api_key)),
                    args.per_region, args.seed, not args.no_audit,
                    progress=lambda message: print(message, file=sys.stderr, flush=True))
            elif args.command == "screen":
                from atia.vision.screen_pipeline import screen_sample
                result = screen_sample(store, args.sample_id, args.batch_size,
                    progress=lambda message: print(message, file=sys.stderr, flush=True))
            elif args.command == "import-review-labels":
                from atia.vision.relevance_review import import_labels
                result = import_labels(store, args.sample_id, args.path)
            elif args.command == "review-report":
                from atia.vision.relevance_review import export_review
                result = export_review(store, args.sample_id, args.reviewer, args.output_dir)
            elif args.command == "sentiment":
                from atia.sentiment.pipeline import run_sentiment
                result = run_sentiment(store, live_client(settings.api_key), args.limit, args.batch_size,
                    args.historical_path, refresh=args.refresh_comments,
                    destination_map=args.destination_map,
                    progress=lambda message: print(message, file=sys.stderr, flush=True))
            elif args.command == "destinations":
                from atia.destinations.storage import DestinationStore
                if args.destination_command == "build":
                    from atia.destinations.geo import GeoPolicy
                    from atia.destinations.pipeline import build_destinations, write_report
                    result = build_destinations(store, GeoPolicy(args.distance_km, args.min_accuracy), args.places,
                        progress=lambda message: print(message, file=sys.stderr, flush=True))
                    write_report(result, args.report)
                else:
                    result = DestinationStore(store).inspect(args.run_id, args.destination_id)
            elif args.command == "intelligence":
                from atia.intelligence.store import IntelligenceStore
                if args.intelligence_command == "restore-images":
                    from atia.intelligence.images import restore_images
                    result = restore_images(store, live_client(settings.api_key), args.limit, args.refresh,
                        progress=lambda message: print(message, file=sys.stderr, flush=True))
                elif args.intelligence_command == "build":
                    from atia.intelligence.signals import build_signals, write_report
                    result = build_signals(store.connection, args.subset_size)
                    write_report(result, args.report)
                    result = result["summary"]
                else:
                    result = IntelligenceStore(store.connection).snapshot(args.kind)
            elif args.command == "demo":
                from atia.demo import init_demo
                result = init_demo(store)
            elif args.command == "images":
                from atia.moderation.display import initialize as initialize_display, review_image as review_display, review_queue
                initialize_display(store.connection)
                if args.image_command == "queue":
                    result = review_queue(store.connection, args.limit)
                else:
                    decision = {"approve": "APPROVED", "reject": "REJECTED", "uncertain": "UNCERTAIN"}[args.decision]
                    result = review_display(store.connection, args.source, args.photo_id, args.sha256, decision, args.reviewer, args.reason,
                        {"viewed_image": args.viewed_image, "image_is_safe": args.confirm_safe, "licence_confirmed": args.confirm_licence})
            elif args.command == "opportunities":
                if args.opportunity_command == "build":
                    from atia.opportunities.curate import build_opportunities
                    result = build_opportunities(store.connection)
                elif args.opportunity_command == "find-images":
                    from atia.opportunities.images import find_images
                    result = find_images(store, live_client(settings.api_key), args.wanted, opportunity_id=args.opportunity)
                elif args.opportunity_command == "recover-rejected":
                    from atia.opportunities.generate import recover_rejected
                    result = recover_rejected(store)
                elif args.opportunity_command == "review-image":
                    from atia.opportunities.images import review_image
                    result = review_image(store.connection, args.opportunity, args.photo_id, args.decision == "accept", args.reviewer, args.reason)
                else:
                    from atia.agents.contracts import Limits
                    from atia.opportunities.generate import build_dossier, estimate, next_opportunity, run_opportunity
                    from atia.opportunities.store import OpportunityStore, initialize
                    initialize(store.connection)
                    chosen = OpportunityStore(store.connection).opportunity(args.opportunity) if args.opportunity else next_opportunity(store.connection)
                    if not chosen:
                        raise ValueError("No opportunity is available")
                    if args.dry_run:
                        dossier = build_dossier(store.connection, chosen)
                        result = {"opportunity": chosen["opportunity_id"], "estimate": estimate(dossier, Limits.load()), "dossier": dossier}
                    elif not args.confirm_paid:
                        raise ValueError("This makes a paid OpenAI request. Use --dry-run, or --confirm-paid to proceed.")
                    else:
                        result = run_opportunity(store, chosen["opportunity_id"], Limits.load())
            elif args.command == "research":
                from atia.research.tool import ResearchStore, run_research, write_report
                if args.research_command == "entities":
                    from atia.research.identity import IdentityStore
                    result = IdentityStore(store).catalogue()
                elif args.research_command == "inspect":
                    if args.provider == "tavily":
                        from atia.research.identity import IdentityStore
                        result = IdentityStore(store).inspect(args.destination_id)
                    else:
                        result = ResearchStore(store).inspect(args.destination_id)
                else:
                    import os
                    from pathlib import Path
                    from atia.research.providers import BraveSearch, EvidenceFileSearch
                    if args.provider == "tavily":
                        if args.resolutions:raise ValueError("Recorded resolutions are not live verification; supply candidate hints through --candidates")
                        from atia.research.tavily import TavilySearch
                        from atia.research.identity import research_locations, write_audit_report
                        provider = TavilySearch(store, os.getenv("TAVILY_API_KEY"), refresh=args.refresh)
                        candidates = json.loads(Path(args.candidates).read_text())
                        result = research_locations(store, provider, candidates, args.destination_ids, args.limit, args.refresh,
                            progress=lambda message: print(message, file=sys.stderr, flush=True))
                        write_audit_report(result, "AUTHORITATIVE_RESEARCH_AUDIT.md" if args.report == "PROMOTIONAL_RESEARCH.md" else args.report)
                    else:
                        if args.provider == "evidence-file":
                            if not args.evidence_file:raise ValueError("--evidence-file is required for recorded-evidence research")
                            provider = EvidenceFileSearch(args.evidence_file)
                        else:
                            provider = BraveSearch(os.getenv("BRAVE_SEARCH_API_KEY"))
                        resolutions = json.loads(Path(args.resolutions).read_text()) if args.resolutions else {}
                        result = run_research(store, provider, resolutions, args.destination_ids, args.limit, args.refresh,
                            progress=lambda message: print(message, file=sys.stderr, flush=True))
                        write_report(result, args.report)
            elif args.command == "moderation":
                from atia.moderation.actions import summary,review,inspect_labels,export_queue,retire_confident
                if args.moderation_command == "evaluate":
                    from atia.moderation.evaluate import evaluate_all
                    result=evaluate_all(store,progress=lambda message:print(message,file=sys.stderr,flush=True))
                elif args.moderation_command == "status":result=summary(store)
                elif args.moderation_command == "retire":result=retire_confident(store)
                elif args.moderation_command == "import-inspections":result=inspect_labels(store,args.path)
                elif args.moderation_command == "queue":result=export_queue(store,args.output_dir)
                else:result=review(store,args.photo_id,args.approve,args.reviewer,args.reason,args.confirm)
            elif args.command == "agent":
                from atia.agents.storage import AgentStore
                if args.agent_command == "discover":
                    if args.scheduled and not args.authorize_paid_run:
                        raise ValueError("Scheduled execution requires explicit --authorize-paid-run; no request was sent")
                    from atia.agents.runner import run_agent
                    result=run_agent(store,refresh=args.refresh,
                        progress=lambda message:print(message,file=sys.stderr,flush=True))
                elif args.agent_command in ("discovery-inspect","campaigns"):
                    from atia.agents.discovery_storage import DiscoveryStore
                    memory=DiscoveryStore(store)
                    result=memory.inspect(args.run_id) if args.agent_command=="discovery-inspect" else memory.campaigns(args.cluster_id)
                elif args.agent_command == "run":
                    from atia.agents.runner import run_agent
                    result = run_agent(store, args.cluster_id, args.goal, refresh=args.refresh, resume_run_id=args.resume_run_id,
                        progress=lambda message: print(message, file=sys.stderr, flush=True))
                elif args.agent_command == "inspect":
                    result = AgentStore(store).inspect(args.run_id)
                else:
                    result = AgentStore(store).memory(args.cluster_id)["proposals"]
            elif args.command == "import-historical":
                result = import_historical(args.path, store)
            else:
                result = {"counts": store.counts()}
            print(json.dumps(result, indent=2, ensure_ascii=False))
            if args.command == "agent" and args.agent_command in ("run","discover") and result.get("errors"):
                return 2
            return 2 if args.command in {"collect", "collect-regions", "analyze", "screen", "sentiment"} and not result["complete"] else 0
    except (FlickrError, ValueError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
