import urllib.request, json
req1 = urllib.request.Request('http://localhost:8000/api/login/pin', data=json.dumps({'pin':'1234'}).encode('utf-8'), headers={'Content-Type':'application/json'})
try:
    token = json.loads(urllib.request.urlopen(req1).read())['token']
    req2 = urllib.request.Request('http://localhost:8000/tables/status', headers={'Authorization': 'Bearer ' + token})
    print(urllib.request.urlopen(req2).read().decode('utf-8'))
except Exception as e:
    print(e)
    if hasattr(e, 'read'):
        print(e.read().decode('utf-8'))
