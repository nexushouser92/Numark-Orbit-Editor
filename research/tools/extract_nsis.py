import sys,struct,lzma,zlib,bz2,os
d=open(sys.argv[1],'rb').read(); out=sys.argv[2]; os.makedirs(out,exist_ok=True)
off=d.find(b'\xef\xbe\xad\xdeNullsoftInst')-4
flags,sig=struct.unpack_from('<II',d,off); hlen,total=struct.unpack_from('<II',d,off+20)
print('fh at',hex(off),'flags',flags,'hlen',hlen,'total',total)
p=off+28; first=d[p:p+16]; print(first.hex())
def lz(buf):
    props=buf[:5]; dec=lzma.LZMADecompressor(lzma.FORMAT_RAW,filters=[{'id':lzma.FILTER_LZMA1,'dict_size':struct.unpack('<I',props[1:5])[0],'lc':props[0]%9,'lp':(props[0]//9)%5,'pb':props[0]//45}])
    return dec.decompress(buf[5:])
blob=d[p:off+total]
if blob[0]==0x5d:
    print('solid lzma'); s=lz(blob); 
    blocks=[];i=0
    while i+4<=len(s):
        n=struct.unpack_from('<I',s,i)[0]; blocks.append(s[i+4:i+4+n]); i+=4+n
else:
    print('non-solid'); blocks=[];i=0
    while i+4<=len(blob):
        n=struct.unpack_from('<I',blob,i)[0]; c=n&0x80000000; n&=0x7fffffff; b=blob[i+4:i+4+n]; i+=4+n
        if c:
            if b[:1]==b'\x5d': b=lz(b)
            else:
                try: b=zlib.decompressobj(-15).decompress(b)
                except Exception as e: print('fail at',i,n,b[:8].hex(),e); b=b''
        blocks.append(b)
for k,b in enumerate(blocks):
    ext='.exe' if b[:2]==b'MZ' else '.bin'
    open(os.path.join(out,f'{k:03d}{ext}'),'wb').write(b); print(k,len(b),b[:8].hex())
