"""Channel-owned Drive hierarchy. Moving files preserves their IDs and links."""
FOLDER_MIME = 'application/vnd.google-apps.folder'
TYPE_FOLDERS = ('Research', 'Script', 'References', 'Images', 'Audio', 'Video', 'Thumbnails', 'Other Assets')
ALIASES = {'research': 'Research', 'script': 'Script', 'scripts': 'Script',
           'references': 'References', 'reference': 'References',
           'images': 'Images', 'static': 'Images', 'grids': 'Images', 'panels': 'Images',
           'storyboards': 'Images', 'portraits': 'Images', 'characters': 'Images',
           'audio': 'Audio', 'voice': 'Audio', 'music': 'Audio', 'sfx': 'Audio', 'sound': 'Audio',
           'final': 'Video', 'final video': 'Video', 'video': 'Video', 'videos': 'Video', 'clips': 'Video',
           'thumbnail': 'Thumbnails', 'thumbnails': 'Thumbnails', 'other assets': 'Other Assets'}


def asset_type(subfolder=None, mime='', filename=''):
    if filename.startswith(('ref_', 'static_ref_')):
        return 'References'
    known = ALIASES.get((subfolder or '').lower())
    if known:
        return known
    if mime.startswith('image/'):
        return 'Images'
    if mime.startswith('audio/'):
        return 'Audio'
    if mime.startswith('video/'):
        return 'Video'
    return 'Other Assets'


def children(client, parent):
    result, token = [], None
    while True:
        page = client.drive_service.files().list(
            q=f"'{parent}' in parents and trashed=false", pageSize=1000,
            fields='nextPageToken,files(id,name,mimeType,parents)', pageToken=token).execute()
        result.extend(page.get('files', []))
        token = page.get('nextPageToken')
        if not token:
            return result


def move(client, file_id, parent):
    service = client.drive_service.files()
    old = service.get(fileId=file_id, fields='id,parents').execute().get('parents', [])
    if old == [parent]:
        return
    kwargs = dict(fileId=file_id, addParents=parent, fields='id,parents')
    if old:
        kwargs['removeParents'] = ','.join(p for p in old if p != parent)
    service.update(**kwargs).execute()


def ensure_folder(client, parent, name):
    found = client.search_folder(name, parent_id=parent)
    return found['id'] if found else client.create_folder(name, parent_id=parent)['id']


def channel_folder(client, tenant_id, name):
    if not tenant_id:
        raise ValueError('A channel identity is required for a video workspace')
    root = getattr(client, 'workspace_root_folder_id', None) or client.parent_folder_id
    label = (name or '').strip() or f"Unnamed Channel — {tenant_id[:8]}"
    service = client.drive_service.files()
    found = service.list(q=f"'{root}' in parents and trashed=false and appProperties has {{ key='storyengine_channel' and value='{tenant_id}' }}", fields='files(id)', pageSize=100).execute().get('files', [])
    folder = found[0]['id'] if found else client.create_folder(label, parent_id=root)['id']
    service.update(fileId=folder, body={'name': label, 'appProperties': {'storyengine_channel': tenant_id}}, fields='id').execute()
    return folder


def video_layout(client, video, folder_name):
    channel = channel_folder(client, str(video['tenant_id']), video.get('channel_name'))
    folder = video.get('drive_folder_id')
    if folder:
        move(client, folder, channel)
        client.drive_service.files().update(fileId=folder, body={'name': folder_name}, fields='id').execute()
    else:
        folder = ensure_folder(client, channel, folder_name)
    types = {name: ensure_folder(client, folder, name) for name in TYPE_FOLDERS}
    return channel, folder, types


def tidy_video(client, folder, types):
    """Rehome existing assets; merge only recognized type folders, never delete files."""
    changes = []
    for item in children(client, folder):
        if item['id'] in types.values():
            continue
        name = item['name']
        if item['mimeType'] == FOLDER_MIME:
            category = ALIASES.get(name.lower())
            if category:
                for child in children(client, item['id']):
                    target = types[asset_type(category, child['mimeType'], child['name'])]
                    move(client, child['id'], target)
                    changes.append({'id': child['id'], 'from': item['id'], 'to': target})
                # Only an observed empty legacy folder is trashed, reversibly.
                if not children(client, item['id']):
                    client.drive_service.files().update(fileId=item['id'], body={'trashed': True}).execute()
                continue
        if 'Machine Roster' in name or name.startswith('02 — Research'):
            category = 'Research'
        elif name.startswith('03 — Script'):
            category = 'Script'
        else:
            category = asset_type(mime=item['mimeType'], filename=name)
        move(client, item['id'], types[category])
        changes.append({'id': item['id'], 'from': folder, 'to': types[category]})
    for item in children(client, types['Images']):
        if item['name'].startswith(('ref_', 'static_ref_')):
            move(client, item['id'], types['References'])
            changes.append({'id': item['id'], 'from': types['Images'], 'to': types['References']})
    return changes
