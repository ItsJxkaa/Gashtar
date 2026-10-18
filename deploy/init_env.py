"""Create the deployment API secret once, without printing it."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    print('Existing .env retained; API key was not rotated.')
else:
    with os.fdopen(fd, 'w') as stream:
        stream.write('CASHGUARD_API_KEY=' + secrets.token_urlsafe(32) + '\n')
    print('API key created in .env. Read it privately and enter it in the UI.')
