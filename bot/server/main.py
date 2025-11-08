from quart import Blueprint, Response, request, render_template, redirect
from math import ceil
from re import match as re_match
import asyncio
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
    base_chunk_size = 1 * 1024 * 1024  # Start with 1MB
    min_chunk = 256 * 1024
    max_chunk = 8 * 1024 * 1024

    if range_header:
        range_match = re_match(r'bytes=(\d+)-(\d*)', range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            if start > end or start >= file_size:
                abort(416, 'Requested range not satisfiable')
        else:
            abort(400, 'Invalid Range header')

    total_bytes_to_stream = end - start + 1
    content_length = total_bytes_to_stream

    headers = {
        'Content-Type': mime_type,
        'Content-Disposition': f'inline; filename={file_name}',
        'Content-Range': f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges': 'bytes',
        'Content-Length': str(content_length),
        'Cache-Control': 'no-store',
        'X-Accel-Buffering': 'no',  # Disable proxy buffering
    }
    status_code = 206 if range_header else 200

    async def smooth_stream():
        """Smart adaptive streaming with predictive buffering."""
        nonlocal base_chunk_size
        bytes_sent = 0
        last_speed = None
        smoothing_factor = 0.85  # higher = smoother response, slower adaptation
        target_buffer_time = 0.25  # seconds of "rest" between chunks

        async for chunk in TelegramBot.stream_media(file, offset=(start // base_chunk_size), limit=ceil(content_length / base_chunk_size)):
            t1 = time.perf_counter()

            # Trim first chunk if needed
            if bytes_sent == 0:
                trim_start = start % base_chunk_size
                if trim_start > 0:
                    chunk = chunk[trim_start:]

            # Send chunk
            yield chunk
            bytes_sent += len(chunk)

            # Measure speed
            t2 = time.perf_counter()
            duration = max(t2 - t1, 0.001)
            speed = len(chunk) / duration  # bytes/sec

            # Smooth average
            if last_speed:
                speed = last_speed * smoothing_factor + speed * (1 - smoothing_factor)
            last_speed = speed

            # Adaptive chunk size control (smooth step)
            target_speed = 800_000  # ideal: 800 KB/s (adjust to your server)
            ratio = min(max(speed / target_speed, 0.5), 2.0)
            base_chunk_size = int(base_chunk_size * ratio)
            base_chunk_size = max(min_chunk, min(max_chunk, base_chunk_size))

            # Small adaptive delay to pace stream smoothly (prevents burst stalls)
            await asyncio.sleep(target_buffer_time / ratio)

            if bytes_sent >= content_length:
                break

    return Response(smooth_stream(), headers=headers, status=status_code)

@bp.route('/stream/<int:file_id>')
async def stream_file(file_id):
    code = request.args.get('code') or abort(401)
    return await render_template('player.html', mediaLink=f'{Server.BASE_URL}/dl/{file_id}?code={code}')
