import json
import uuid
from atia.models import utc_now

NAMESPACE=uuid.UUID('0396421a-2332-4f4d-a452-139124362e79')


class DestinationStore:
    def __init__(self,store,initialize=True):
        self.db=store.connection;self.db.execute('PRAGMA foreign_keys=ON')
        if not initialize:return
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS destination_runs (
          run_id TEXT PRIMARY KEY,policy_key TEXT NOT NULL,policy TEXT NOT NULL,input_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,report TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS destination_entities (
          destination_id TEXT PRIMARY KEY,policy_key TEXT NOT NULL,anchor_photo_id TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS destination_snapshots (
          run_id TEXT NOT NULL,destination_id TEXT NOT NULL,name TEXT NOT NULL,level TEXT NOT NULL,
          evidence TEXT NOT NULL,PRIMARY KEY(run_id,destination_id),
          FOREIGN KEY(run_id) REFERENCES destination_runs(run_id),
          FOREIGN KEY(destination_id) REFERENCES destination_entities(destination_id));
        CREATE TABLE IF NOT EXISTS destination_photo_assignments (
          run_id TEXT NOT NULL,source TEXT NOT NULL,photo_id TEXT NOT NULL,destination_id TEXT,
          unassigned_reason TEXT,geographic_evidence TEXT NOT NULL,
          PRIMARY KEY(run_id,source,photo_id),
          FOREIGN KEY(run_id) REFERENCES destination_runs(run_id),
          FOREIGN KEY(source,photo_id) REFERENCES photos(source,photo_id),
          FOREIGN KEY(run_id,destination_id) REFERENCES destination_snapshots(run_id,destination_id));
        ''');self.db.commit()

    def previous(self,key):
        row=self.db.execute('SELECT run_id FROM destination_runs WHERE policy_key=? ORDER BY created_at DESC LIMIT 1',(key,)).fetchone()
        if row is None:return {}
        groups={}
        for member in self.db.execute('SELECT destination_id,photo_id FROM destination_photo_assignments WHERE run_id=? AND destination_id IS NOT NULL',(row['run_id'],)):
            groups.setdefault(member['destination_id'],set()).add(member['photo_id'])
        return groups

    def identities(self,groups,key):
        previous=self.previous(key);used=set();result=[]
        # Reuse IDs with largest membership overlap. On splits/merges, preserve one
        # identity and record all parent candidates; old snapshots remain intact.
        ordered=sorted(enumerate(groups),key=lambda item:(-max([len({p['photo_id'] for p in item[1]}&members) for members in previous.values()] or [0]),min(p['photo_id'] for p in item[1])))
        identities={}
        for index,group in ordered:
            ids={p['photo_id'] for p in group}
            overlaps=sorted([(len(ids&members),identifier) for identifier,members in previous.items() if ids&members],key=lambda v:(-v[0],v[1]))
            identifier=next((identifier for _,identifier in overlaps if identifier not in used),None)
            if identifier is None:
                identifier='dest-'+uuid.uuid5(NAMESPACE,key+':'+min(ids)).hex[:16]
                if identifier in used:
                    identifier='dest-'+uuid.uuid5(NAMESPACE,key+':'+','.join(sorted(ids))).hex[:16]
            used.add(identifier)
            identities[index]=(identifier,[parent for _,parent in overlaps])
        return [identities[i] for i in range(len(groups))]

    def save(self,report,policy,key,input_hash,points):
        run=report['run_id']
        with self.db:
            self.db.execute('INSERT INTO destination_runs VALUES(?,?,?,?,?,?)',(run,key,json.dumps(policy),input_hash,utc_now(),json.dumps(report,ensure_ascii=False)))
            assigned={}
            for group in report['destinations']:
                identifier=group['destination_id']
                self.db.execute('INSERT OR IGNORE INTO destination_entities VALUES(?,?,?,?)',(identifier,key,min(group['photo_ids']),utc_now()))
                self.db.execute('INSERT INTO destination_snapshots VALUES(?,?,?,?,?)',(run,identifier,group['name'],group['level'],json.dumps(group,ensure_ascii=False)))
                for photo_id in group['photo_ids']:assigned[photo_id]=identifier
            for point in points:
                self.db.execute('INSERT INTO destination_photo_assignments VALUES(?,?,?,?,?,?)',
                    (run,point['source'],point['photo_id'],assigned.get(point['photo_id']) if point['unassigned_reason'] is None else None,point['unassigned_reason'],json.dumps(point,ensure_ascii=False)))

    def inspect(self,run_id=None,destination_id=None):
        if run_id is None:
            row=self.db.execute('SELECT run_id FROM destination_runs ORDER BY created_at DESC LIMIT 1').fetchone()
            if row is None:raise ValueError('No destination runs; run destinations build first')
            run_id=row['run_id']
        row=self.db.execute('SELECT report FROM destination_runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:raise ValueError('Unknown destination run')
        report=json.loads(row['report'])
        if destination_id:
            group=next((g for g in report['destinations'] if g['destination_id']==destination_id),None)
            if group is None:raise ValueError('Destination is not present in this run')
            return group
        return report
