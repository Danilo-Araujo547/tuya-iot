import hashlib
import io
import warnings

from fastapi import APIRouter, Request, Response, HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select, func

from .db import DB, Appearance, Wallpaper
from .security import authenticate

router = APIRouter(prefix='/api/v1/appearance')
PRESETS = {'solar', 'studio', 'nordic'}
MAX_BYTES = 3 * 1024 * 1024


def admin(request):
    if authenticate(request) != 'admin':
        raise HTTPException(403, 'Somente o administrador pode alterar o papel de parede')


def serialized(db):
    preference = db.get(Appearance, 'dashboard')
    rows = db.execute(select(Wallpaper.id, Wallpaper.name).order_by(Wallpaper.created.desc())).all()
    return {'selected': preference.selected if preference else 'solar',
            'wallpapers': [{'id': r.id, 'name': r.name, 'url': '/api/v1/appearance/wallpapers/' + r.id} for r in rows]}


@router.get('')
def get_appearance(request: Request):
    authenticate(request)
    with DB() as db:
        return serialized(db)


class Choice(BaseModel):
    id: str = Field(min_length=1, max_length=64)


@router.put('')
def choose(body: Choice, request: Request):
    admin(request)
    with DB.begin() as db:
        if body.id not in PRESETS and not db.get(Wallpaper, body.id):
            raise HTTPException(404, 'Papel de parede não encontrado')
        preference = db.execute(select(Appearance).where(Appearance.id == 'dashboard').with_for_update()).scalar_one()
        preference.selected = body.id
        db.flush()
        return serialized(db)


@router.post('/wallpapers', status_code=201)
async def upload(request: Request):
    admin(request)
    if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
        raise HTTPException(415, 'Envie uma imagem JPEG preparada pelo dashboard')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, 'Imagem preparada excede 3 MB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != 'JPEG' or source.width * source.height > 12_000_000:
                    raise ValueError('Invalid JPEG')
                image = ImageOps.exif_transpose(source).convert('RGB')
                image.thumbnail((1920, 1920))
                result = io.BytesIO()
                image.save(result, format='JPEG', quality=85)
                content = result.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'Não foi possível validar a imagem')
    identifier = hashlib.sha256(content).hexdigest()
    with DB.begin() as db:
        preference = db.execute(select(Appearance).where(Appearance.id == 'dashboard').with_for_update()).scalar_one()
        if not db.get(Wallpaper, identifier):
            if db.scalar(select(func.count()).select_from(Wallpaper)) >= 20:
                raise HTTPException(409, 'A galeria já contém 20 imagens')
            db.add(Wallpaper(id=identifier, name='Minha foto', image=content))
        preference.selected = identifier
        db.flush()
        return serialized(db)


@router.get('/wallpapers/{identifier}')
def image(identifier: str, request: Request):
    authenticate(request)
    with DB() as db:
        row = db.get(Wallpaper, identifier)
        if not row:
            raise HTTPException(404, 'Imagem não encontrada')
        return Response(content=row.image, media_type='image/jpeg', headers={
            'Cache-Control': 'private, max-age=86400', 'X-Content-Type-Options': 'nosniff'})
