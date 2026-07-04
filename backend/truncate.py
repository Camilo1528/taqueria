with open('api.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for l in lines:
    if l.startswith('@app.post("/api/delivery/assign/{order_id}")'):
        break
    new_lines.append(l)

with open('api.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
