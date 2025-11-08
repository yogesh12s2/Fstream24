from quart import Blueprint, Response, request, render_template, redirect
from math import ceil
from re import match as re_match
import time
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
    file = await get_message(file_id) or abort(404)
    code = request.args.get('code') or abort(401)
    range_header = request.headers.get('Range')

    if code != file.caption.split('/')[0]:
        abort(403)

    file_name, file_size, mime_type = get_file_properties(file)

    start = 0
    end = file_size - 1
    base_chunk_size = 1 * 1024 * 1024  # start with 1MB

    if range_header:
        range_match = re_match(r'bytes=(\d+)-(\d*)', range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            if start > end or start >= file_size:
                abort(416, 'Requested range not satisfiable')
        else:
            abort(400, 'Invalid Range header')

    offset_chunks = start // base_chunk_size
    total_bytes_to_stream = end - start + 1
    chunks_to_stream = ceil(total_bytes_to_stream / base_chunk_size)

    content_length = total_bytes_to_stream
    headers = {
        'Content-Type': mime_type,
        'Content-Disposition': f'inline; filename={file_name}',
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(content_length),
        'Cache-Control': 'no-store',
    }
    status_code = 206 if range_header else 200

    async def adaptive_stream():
        nonlocal base_chunk_size
        bytes_streamed = 0
        chunk_index = 0
        last_speed = None

        async for chunk in TelegramBot.stream_media(file, offset=offset_chunks, limit=chunks_to_stream):
            # Measure transfer speed
            t1 = time.perf_counter()
            
            if chunk_index == 0:  # Trim first chunk
                trim_start = start % base_chunk_size
                if trim_start > 0:
                    chunk = chunk[trim_start:]

            yield chunk
            bytes_streamed += len(chunk)
            chunk_index += 1

            # Measure speed after yielding
            t2 = time.perf_counter()
            duration = max(t2 - t1, 0.001)
            speed = len(chunk) / duration  # bytes per second

            # Smooth network speed adaptation
            if last_speed:
                speed = (last_speed * 0.7) + (speed * 0.3)
            last_speed = speed

            # Adjust chunk size adaptively
            if speed < 300_000:  # < 300 KB/s → slow connection
                base_chunk_size = max(256 * 1024, base_chunk_size // 2)
            elif speed > 1_000_000:  # > 1 MB/s → good connection
                base_chunk_size = min(4 * 1024 * 1024, base_chunk_size * 2)

    return Response(adaptive_stream(), headers=headers, status=status_code)


@bp.route('/stream/<int:file_id>')
async def stream_file(file_id):
    code = request.args.get('code') or abort(401)
    return await render_template('player.html', mediaLink=f'{Server.BASE_URL}/dl/{file_id}?code={code}')
