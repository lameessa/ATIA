"""Private, local inspection aids. Never served by the dashboard or auto-approved."""
import json
from pathlib import Path
from PIL import Image,ImageDraw
from atia.config import Settings
from atia.storage.sqlite import PhotoStore


def main():
    settings=Settings.load();out=Path('data/quarantine/inspection');out.mkdir(parents=True,exist_ok=True)
    with PhotoStore(settings.db_path) as store:
        rows=[dict(r) for r in store.connection.execute('''SELECT p.photo_id,p.region,p.latitude,p.longitude,a.image_path,a.image_sha256,m.evaluation_json
          FROM photos p LEFT JOIN moderation_asset_cache a ON a.photo_id=p.photo_id
          JOIN photo_moderation m ON m.photo_id=p.photo_id WHERE p.source='flickr_live' ORDER BY p.photo_id''')]
    mapping=[]
    for offset in range(0,len(rows),10):
        page=Image.new('RGB',(900,1450),'white');draw=ImageDraw.Draw(page)
        subset=rows[offset:offset+10]
        for index,row in enumerate(subset):
            x=(index%2)*450;y=(index//2)*290
            draw.text((x+8,y+6),row['photo_id']+' / '+str(row['region'] or 'region inferred later'),fill='black')
            if row['image_path']:
                with Image.open(row['image_path']) as opened:
                    thumb=opened.convert('RGB');thumb.thumbnail((430,252));page.paste(thumb,(x+(450-thumb.width)//2,y+28));thumb.close()
            else:draw.text((x+20,y+80),'IMAGE UNAVAILABLE - RETAIN QUARANTINE',fill='black')
        path=out/f'batch-{offset//10+1:02d}.jpg';page.save(path,quality=90);page.close()
        mapping.append({'sheet':str(path),'photos':[{'photo_id':r['photo_id'],'image_sha256':r['image_sha256']} for r in subset]})
    (out/'manifest.json').write_text(json.dumps(mapping,indent=2));print(json.dumps(mapping,indent=2))


if __name__=='__main__':main()
