import base64
import collections
import re
import struct
import sys
import zipfile
import zlib


def walk(b):
    assert b[:8]==b'PCFFGRA4', b[:8]
    i=8; tags=collections.Counter(); depth=0; maxd=0
    while i < len(b):
        if i+2>len(b): return False,i,tags,maxd
        t=struct.unpack_from('<H',b,i)[0]
        if t & 0x4000 and not t & 0x8000:
            i+=2; tags[t]+=1; depth-=1; continue
        if i+6>len(b): return False,i,tags,maxd
        L=struct.unpack_from('<I',b,i+2)[0]
        tags[t]+=1
        if t & 0x8000: depth+=1; maxd=max(maxd,depth)
        i+=6+L
    return i==len(b), i, tags, maxd
blobs=[]
for p in sys.argv[1:]:
    if p.endswith(('.prism',)):
        z=zipfile.ZipFile(p)
        for n in z.namelist():
            if n.endswith('data.bin') and ('graphs/' in n or 'layouts/' in n): blobs.append((p+':'+n, z.read(n)))
    elif p.endswith('.pzfx'):
        t=open(p,encoding='utf-8',errors='replace').read()
        m=re.search(r'<Template[^>]*>(.*?)</Template>',t,re.DOTALL)
        if m: blobs.append((p, zlib.decompress(base64.b64decode(m.group(1)))))
ok=0; alltags=collections.Counter()
for name,b in blobs:
    good,end,tags,maxd=walk(b); ok+=good; alltags.update(tags)
    if not good: print('FAIL',name,end,len(b))
print(f'{ok}/{len(blobs)} blobs fully covered by tag-length framing; distinct tags={len(alltags)}; total bytes={sum(len(b) for _,b in blobs)}')
print('top tags', [(hex(t),c) for t,c in alltags.most_common(15)])
