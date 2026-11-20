import json
from datetime import datetime
import re

# Matches timestamps like [DD/MM/YYYY, HH:MM:SS] or D/M/YYYY HH:MM:SS - (including AM/PM & Unicode spaces)
TIMESTAMP_PATTERN = re.compile(
    r'^[\u200e\u200f\s]*\[?(\d{1,4}[/-]\d{1,2}[/-]\d{1,4},?[\s\u00a0\u2009\u202f]+\d{1,2}:\d{2}(?::\d{2})?(?:[\s\u202f]?[APap][Mm])?)\]?(?:\s*-\s*|\s+)(.*)'
)

# Matches "Sender:" followed by optional whitespace and invisible directional marks
SENDER_SPLIT_PATTERN = re.compile(
    r'^([^:\n]+?):[\s\u200e\u200f\u202a-\u202e\u2066-\u2069]*(.*)$',
    re.DOTALL
)

INVISIBLE_CHARS_PATTERN = re.compile(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]')

# Common system message markers (Traditional Chinese + English)
SYSTEM_MESSAGE_PATTERNS = [
    r'訊息和通話經端對端加密',
    r'Messages and calls are end-to-end encrypted',
    r'建立了此群組',
    r'created group',
    r'已新增',
    r'added\s',
    r'已移除',
    r'removed\s',
    r'已離開',
    r'left$',
    r'已將一個訊息置頂',
    r'pinned a message',
    r'已變更',
    r'changed the',
    r'安全碼已變更',
    r'security code changed',
    r'此訊息已刪除。'
]
SYSTEM_REGEX = re.compile('|'.join(SYSTEM_MESSAGE_PATTERNS), re.IGNORECASE)

MEDIA_MARKERS = (
    '<Media omitted>',
    '<attached:',
    '圖片已略去',
    '影片已略去',
    '文件已略去',
    '音訊已略去',
    '語音訊息已略去',
    '貼圖已略去',
    'GIF 已略去',
)

SPACE_VARIANTS = re.compile(r'[\s\u00a0\u2009\u202f]+')
INVISIBLE_CHARS_PATTERN = re.compile(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]')

INPUT_FORMATS = (
    '%d/%m/%Y %H:%M:%S',
    '%d/%m/%Y %H:%M',
    '%m/%d/%Y %H:%M:%S',
    '%m/%d/%Y %H:%M',
    '%d/%m/%y %H:%M:%S',
    '%d/%m/%y %H:%M',
    '%m/%d/%y %H:%M:%S',
    '%m/%d/%y %H:%M',
)

def is_whatsapp_message(txt_path):
    with open(txt_path, 'r', encoding='utf-8') as f:
        if TIMESTAMP_PATTERN.match(f[0]):
            return True
    return False

def normalize_whatsapp_timestamp(raw_ts: str) -> str:
    cleaned = INVISIBLE_CHARS_PATTERN.sub('', raw_ts)
    cleaned = cleaned.replace(',', ' ')
    cleaned = SPACE_VARIANTS.sub(' ', cleaned).strip()

    dt = None
    for fmt in INPUT_FORMATS:
        try:
            dt = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        return SPACE_VARIANTS.sub(' ', cleaned).strip()

    return f'{dt.day}/{dt.month}/{dt.strftime("%Y")} {dt.strftime("%H:%M:%S")}'

def strip_invisible(text: str) -> str:
    return INVISIBLE_CHARS_PATTERN.sub('', text).strip()

def is_system_message(sender: str, message: str) -> bool:
    if sender in ('System', '你', 'You'):
        return True
    if SYSTEM_REGEX.search(message):
        return True
    return False

def parse_whatsapp_to_json(txt_path):
    messages = []
    current_msg = None

    with open(txt_path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.rstrip('\r\n')
            clean_line = strip_invisible(line)

            match = TIMESTAMP_PATTERN.match(clean_line)
            if match:
                # Save the previous valid message before moving to the new timestamped line
                if current_msg:
                    messages.append(current_msg)
                    current_msg = None

                timestamp, content = match.groups()
                timestamp = normalize_whatsapp_timestamp(timestamp)
                content_clean = strip_invisible(content)

                sender_match = SENDER_SPLIT_PATTERN.match(content)
                if sender_match:
                    raw_sender, raw_msg = sender_match.groups()
                    sender = strip_invisible(raw_sender)
                    message = strip_invisible(raw_msg)
                else:
                    # Temporary value only for checking if the line is a system event
                    if is_system_message('System', content_clean) or any(
                        marker in content_clean for marker in MEDIA_MARKERS
                    ):
                        continue
                    sender = 'System'
                    message = content_clean

                if is_system_message(sender, message) or any(
                    marker in message for marker in MEDIA_MARKERS
                ):
                    continue

                current_msg = {
                    'timestamp': timestamp,
                    'sender': sender,
                    'message': message,
                    'selected':True
                }
            else:
                # Continuation line inside a multi-line message
                if current_msg:
                    clean_cont = strip_invisible(line)
                    if clean_cont:
                        current_msg['message'] += '\n' + clean_cont

        if current_msg:
            messages.append(current_msg)
        return messages

#     with open(json_path, 'w', encoding='utf-8') as f:
#         json.dump(messages, f, ensure_ascii=False, indent=2)


# # Usage
# parse_whatsapp_to_json('text_record/_chat_2.txt', 'text_record/whatsapp_chat_2.json')