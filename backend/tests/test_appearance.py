import io
from PIL import Image
from fastapi.testclient import TestClient
from app.db import DB, ApiKey, Wallpaper
from app.security import digest


def jpeg():
    result=io.BytesIO()
    Image.new('RGB',(80,60),'#8ac7cf').save(result,format='JPEG')
    return result.getvalue()


def test_wallpaper_persists_across_sessions_and_presets(logged):
    image=jpeg()
    saved=logged.post('/api/v1/appearance/wallpapers',content=image,headers={'Content-Type':'image/jpeg'})
    assert saved.status_code==201
    identifier=saved.json()['selected']
    url=saved.json()['wallpapers'][0]['url']
    assert logged.get(url).headers['content-type']=='image/jpeg'
    assert logged.put('/api/v1/appearance',json={'id':'studio'}).status_code==200
    assert len(logged.get('/api/v1/appearance').json()['wallpapers'])==1
    from app.main import app
    with TestClient(app,base_url='https://testserver') as second:
        second.post('/api/v1/auth/login',headers={'Origin':'https://testserver'},json={'username':'admin','password':'correct-password-123'})
        assert second.get('/api/v1/appearance').json()['selected']=='studio'
        assert second.get(url).status_code==200
    selected=logged.put('/api/v1/appearance',json={'id':identifier})
    assert selected.json()['selected']==identifier
    duplicate=logged.post('/api/v1/appearance/wallpapers',content=image,headers={'Content-Type':'image/jpeg'})
    assert len(duplicate.json()['wallpapers'])==1
    with DB() as db:
        assert db.query(Wallpaper).count()==1


def test_wallpaper_rejects_invalid_requests_and_csrf(logged):
    assert logged.put('/api/v1/appearance',json={'id':'missing'}).status_code==404
    assert logged.post('/api/v1/appearance/wallpapers',content=b'not-jpeg',headers={'Content-Type':'image/jpeg'}).status_code==422
    assert logged.post('/api/v1/appearance/wallpapers',content=b'<svg/>',headers={'Content-Type':'image/svg+xml'}).status_code==415
    assert logged.post('/api/v1/appearance/wallpapers',content=b'x'*(3*1024*1024+1),headers={'Content-Type':'image/jpeg'}).status_code==413
    assert logged.put('/api/v1/appearance',json={'id':'studio'},headers={'X-CSRF-Token':'wrong'}).status_code==403
    assert logged.get('/api/v1/appearance').json()['selected']=='solar'


def test_api_keys_cannot_change_wallpapers(client):
    with DB.begin() as db:
        db.add(ApiKey(hash=digest('read-only'),name='reader',control=False))
    headers={'Authorization':'Bearer read-only'}
    assert client.get('/api/v1/appearance',headers=headers).status_code==200
    assert client.put('/api/v1/appearance',json={'id':'studio'},headers=headers).status_code==403
    assert client.post('/api/v1/appearance/wallpapers',content=jpeg(),headers={**headers,'Content-Type':'image/jpeg'}).status_code==403
    assert client.get('/api/v1/appearance/wallpapers/missing').status_code==401


def test_gallery_limit_keeps_existing_images(logged):
    with DB.begin() as db:
        for i in range(20):
            db.add(Wallpaper(id=str(i),name='Saved',image=jpeg()))
    result=logged.post('/api/v1/appearance/wallpapers',content=jpeg(),headers={'Content-Type':'image/jpeg'})
    assert result.status_code==409
    assert logged.get('/api/v1/appearance').json()['selected']=='solar'
