from quart import Blueprint, Response, request, render_template, redirect
from re import match as re_match
from .error import abort
from bot import TelegramBot
from bot.config import Telegram, Server
from bot.modules.telegram import get_message, get_file_properties

bp = Blueprint('main', __name__)

# ------------------------
# Homepage redirect
# ------------------------
@bp.route('/')
async def home():
    return redirect(f'https://t.me/{Telegram.BOT_USERNAME}')

# ------------------------
# Stream endpoint (used by video player)
# ------------------------
@bp.route('/dl/<int:file_id>')
async def transmit_file(file_id):
    # Get Telegram file
    file = await get_message(file_id) or abort(404)
    code = request.args.get('code') or abort(401)
    range_header = request.headers.get('Range')

    # Security check
    if code != file.caption.split('/')[0]:
        abort(403)

    # Get metadata
    file_name, file_size, mime_type = get_file_properties(file)

    # --- Handle Range ---
    start = 0
    end = file_size - 1
    if range_header:
        range_match = re_match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            if range_match.group(2):
                end = int(range_match.group(2))
            if start > end or start >= file_size:
                abort(416, "Requested range not satisfiable")
        else:
            abort(400, "Invalid Range header")

    content_length = end - start + 1

    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Disposition": f'inline; filename="{file_name}"'
    }
    status_code = 206 if range_header else 200

    # --- Stream generator ---
    async def file_stream():
        # Fetch bytes directly from Telegram, in small buffered parts
        async for chunk in TelegramBot.stream_media(
            file,
            offset_bytes=start,
            limit_bytes=content_length
        ):
            yield chunk

    return Response(file_stream(), headers=headers, status=status_code)


# ------------------------
# Player page
# ------------------------
@bp.route('/stream/<int:file_id>')
async def stream_file(file_id):
    code = request.args.get('code') or abort(401)
    return await render_template(
        'player.html',
        mediaLink=f'{Server.BASE_URL}/dl/{file_id}?code={code}'
    )
