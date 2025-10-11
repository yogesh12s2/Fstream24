from quart import Blueprint, Response, request, render_template, redirect, current_app
from math import ceil
from re import match as re_match
from .error import abort
from bot import TelegramBot
from bot.config import Telegram, Server
from bot.modules.telegram import get_message, get_file_properties

bp = Blueprint('main', __name__)

@bp.route('/')
async def home():
    return redirect(f'https://t.me/{Telegram.BOT_USERNAME}')


@bp.route('/dl/<int:file_id>')
async def transmit_file(file_id):
    # Get Telegram message (media)
    file = await get_message(file_id) or abort(404)

    # Auth check
    code = request.args.get('code') or abort(401)
    if code != (file.caption.split('/')[0] if file.caption else None):
        abort(403)

    # Get file metadata
    file_name, file_size, mime_type = get_file_properties(file)
    range_header = request.headers.get('Range')

    start = 0
    end = file_size - 1
    chunk_size = 1 * 1024 * 1024  # 1 MB chunk

    # Handle HTTP Range requests
    if range_header:
        range_match = re_match(r'bytes=(\d+)-(\d*)', range_header)
        if range_match:
            start = int(range_match.group(1))
            if range_match.group(2):
                end = int(range_match.group(2))
            if start > end or start >= file_size:
                abort(416, 'Requested range not satisfiable')
        else:
            abort(400, 'Invalid Range header')

    offset_chunks = start // chunk_size
    total_bytes = end - start + 1
    chunks_to_stream = ceil(total_bytes / chunk_size)

    headers = {
        'Content-Type': mime_type,
        'Content-Disposition': f'inline; filename="{file_name}"',
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(total_bytes),
        'Cache-Control': 'public, max-age=3600, immutable',
        'Connection': 'keep-alive'
    }

    status_code = 206 if range_header else 200

    async def file_stream():
        """Async generator to stream Telegram file in small chunks."""
        bytes_sent = 0
        async for chunk in TelegramBot.stream_media(file, offset=offset_chunks, limit=chunks_to_stream):
            # Skip unwanted bytes at start
            if bytes_sent == 0 and start % chunk_size:
                trim = start % chunk_size
                chunk = chunk[trim:]

            remaining = total_bytes - bytes_sent
            if remaining <= 0:
                break

            if len(chunk) > remaining:
                chunk = chunk[:remaining]

            yield chunk
            bytes_sent += len(chunk)

    return Response(file_stream(), headers=headers, status=status_code)


@bp.route('/stream/<int:file_id>')
async def stream_file(file_id):
    code = request.args.get('code') or abort(401)
    return await render_template(
        'player.html',
        mediaLink=f'{Server.BASE_URL}/dl/{file_id}?code={code}'
    )
