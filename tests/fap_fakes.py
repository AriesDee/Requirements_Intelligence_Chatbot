"""Test doubles for the FAP Manager tools: a fake UKG that behaves like the verified API.

Behaviour copied from what was observed on NPR1:
  GET ?name=X      exact name match; an unknown name gives HTTP 404 WCO-127822
  PUT /{id}        REPLACES the whole permission list
  DELETE /{id}     204; HTTP 400 WCO-127807 when the FAP is assigned to users
  bad action       HTTP 400 WCO-127815 (does not say which control point)
  built-in FAPs    negative ids (Super Access = -1)
"""
import json
from urllib.parse import unquote

VALID_ACTIONS = {'ADD', 'EDIT', 'DELETE', 'VIEW', 'ALLOWED'}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body) if body is not None else ''

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._body is None:
            raise ValueError('no body')
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f'HTTP {self.status_code}')


def perm(key, action, scope='ALL'):
    return {'controlPointKey': key, 'actionName': action, 'scopeName': scope}


def super_access():
    """Built-in reference: every control point with every valid action."""
    perms = [perm('PERSON', a) for a in ('ADD', 'EDIT', 'DELETE', 'VIEW')]
    perms += [perm('TIMECARD', a) for a in ('EDIT', 'VIEW')]
    perms += [perm('REPORTS', 'ALLOWED')]
    return {'id': -1, 'name': 'Super Access', 'description': 'built in', 'isDefault': True,
            'permissionTypes': perms}


class FakeUKG:
    """Stands in for ukg_env's client: env, base_url, grant_type, profile_name, mode, request()."""

    def __init__(self, env='NPR1', faps=None):
        self.env, self.base_url, self.grant_type = env, f'{env.lower()}.example.com', 'client_credentials'
        self.profile_name, self.mode, self.keyvault_name = None, 'local', None
        self.faps = {f['id']: f for f in (faps if faps is not None else [super_access()])}
        self.next_id = 1000
        self.in_use: set[int] = set()
        self.calls: list[tuple[str, str]] = []

    def generate_access_token(self):
        pass

    def add(self, name, perms, fap_id=None, description=None):
        fap_id = fap_id or self.next_id
        self.next_id = max(self.next_id, fap_id) + 1
        self.faps[fap_id] = {'id': fap_id, 'name': name, 'description': description or name,
                             'isDefault': False, 'permissionTypes': list(perms)}
        return fap_id

    def by_name(self, name):
        return next((f for f in self.faps.values() if f['name'].lower() == name.lower()), None)

    def request(self, method, path, json=None, **_):
        self.calls.append((method, path))
        base, _, query = path.partition('?')
        fap_id = base.rsplit('/', 1)[1] if base.rsplit('/', 1)[1].lstrip('-').isdigit() else None
        if method == 'GET':
            if query.startswith('name='):
                name = unquote(query[5:])
                rec = self.by_name(name)
                if rec is None:
                    return FakeResponse(404, {'errorCode': 'WCO-127822', 'message':
                                              f'A Function Access Profile does not exist with specified name: {name}.'})
                return FakeResponse(200, [rec])
            # the list call returns id, name, description only (as seen on NPR1)
            return FakeResponse(200, [{k: v for k, v in f.items() if k in ('id', 'name', 'description')}
                                      for f in self.faps.values()])
        if method == 'POST':
            bad = self._bad_action(json)
            if bad:
                return bad
            if self.by_name(json['name']):
                return FakeResponse(400, {'errorCode': 'WCO-DUP', 'message': 'name exists'})
            new_id = self.add(json['name'], json['permissionTypes'], description=json.get('description'))
            return FakeResponse(201, self.faps[new_id])
        fid = int(fap_id)
        if fid not in self.faps:
            return FakeResponse(404, {'errorCode': 'WCO-NF', 'message': 'not found'})
        if method == 'PUT':
            bad = self._bad_action(json)
            if bad:
                return bad
            self.faps[fid].update(json)               # replaces permissionTypes entirely
            return FakeResponse(200, self.faps[fid])
        if method == 'DELETE':
            if fid in self.in_use or fid < 0:
                return FakeResponse(400, {'errorCode': 'WCO-127807', 'message':
                                          'This Function Access Profile is already in use or Gold Data, '
                                          'so could not be deleted.'})
            del self.faps[fid]
            return FakeResponse(204)
        raise AssertionError(f'unexpected {method} {path}')

    @staticmethod
    def _bad_action(payload):
        for p in payload.get('permissionTypes', []):
            if p['actionName'] not in VALID_ACTIONS:
                return FakeResponse(400, {'errorCode': 'WCO-127815', 'message':
                                          f'Illegal value provided for actionName: {p["actionName"]}.'})
        return None
