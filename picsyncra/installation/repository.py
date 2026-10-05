"""Fixed update repository and bounded API reader for stable recovery tools."""
import json
from urllib.request import Request, urlopen

GITHUB_OWNER = 'NefilimPL'
GITHUB_REPOSITORY = 'NefilimPL/PicSyncra'


def fetch_release_json(path):
    if not path.startswith('/repos/' + GITHUB_REPOSITORY + '/releases'):
        raise ValueError('Unsupported update API path.')
    request=Request('https://api.github.com'+path,headers={'Accept':'application/vnd.github+json',
        'User-Agent':'PicSyncra-installed/2','X-GitHub-Api-Version':'2022-11-28'})
    with urlopen(request,timeout=8) as response:
        raw=response.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Release API response too large.')
    return json.loads(raw)
