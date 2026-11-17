"""Native original trophy toast regression fixture. Author: matymeatboy."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]


def test_popup_queue_pixels_and_bounds(tmp_path):
    assert (ROOT/'src/tj_trophy_popup.cpp').exists(), 'CPU popup implementation missing'
    code = r'''
#include "tj_trophy_popup.h"
#include <cassert>
#include <vector>
#include <cstring>
int main(){
 std::vector<unsigned char> b(384*96*4+32,0xCD);
 tj_trophy_popup_configure("missing/catalog.bin","es");
 assert(!tj_trophy_popup_render(b.data(),1536,384,96,0));
 tj_trophy_popup_notify(13,"invalid","");
 assert(!tj_trophy_popup_render(b.data(),1536,384,96,0));
 for(unsigned i=0;i<13;i++){tj_trophy_popup_notify(i,"Trofeo: acción 日本語","");tj_trophy_popup_notify(i,"duplicate","");}
 assert(!tj_trophy_popup_render(b.data(),1,384,96,0));
 for(unsigned i=0;i<13;i++){
  unsigned long long t=100000+i*5000;
  assert(tj_trophy_popup_render(b.data(),1536,384,96,t));
  assert(tj_trophy_popup_render(b.data(),1536,384,96,t+250));
  unsigned occupied=0;
  for(unsigned j=0;j<384*96*4;j+=4){assert(b[j]<=b[j+3]);assert(b[j+1]<=b[j+3]);assert(b[j+2]<=b[j+3]);occupied+=b[j+3]!=0;}
  assert(occupied>20000);
 }
 assert(!tj_trophy_popup_render(b.data(),1536,384,96,165000));
 tj_trophy_popup_notify(0,"duplicate after expiry","");
 assert(!tj_trophy_popup_render(b.data(),1536,384,96,170000));
 for(unsigned j=384*96*4;j<b.size();j++)assert(b[j]==0xCD);
}
'''
    src=tmp_path/'popup.cpp';src.write_text(code,encoding='utf-8')
    exe=tmp_path/'popup.exe'
    result=subprocess.run([r'C:\Program Files\LLVM\bin\clang++.exe','-std=c++20',str(src),str(ROOT/'src/tj_trophy_popup.cpp'),'-I'+str(ROOT/'src'),'-o',str(exe),'-lgdi32','-lwindowscodecs','-lole32','-luser32'],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    subprocess.run([str(exe)],check=True)



@pytest.mark.parametrize("icon_kind", ["corrupt", "valid", "oversized"])
def test_preview_real_catalog_name_and_corrupt_png(tmp_path, icon_kind):
    import struct
    def u(n): return struct.pack('>I',n)
    def s(v):
        b=v.encode('utf-8');return u(len(b))+b
    catalog=b'LJTRP01\0'+u(13)+s('NPWR01344_00')+s('Test')+s('Fixture')
    for i in range(13):
        catalog+=u(i)+u(1 if i==0 else 3)+u(0)+u(0xffffffff)+s('Acción 日本語 '+str(i))+s('Description')+s('icons/TROP%03d.PNG'%i)
    (tmp_path/'catalog.bin').write_bytes(catalog)
    (tmp_path/'icons').mkdir()
    import zlib
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\0\0\xff'))+chunk(b'IEND',b'')
    (tmp_path/'icons/TROP000.PNG').write_bytes(png if icon_kind=='valid' else b'X'*(1024*1024+1) if icon_kind=='oversized' else b'not PNG')
    src=tmp_path/'preview.cpp'
    src.write_text(r'''
#include "tj_trophy_popup.h"
#include <vector>
#include <cassert>
#include <fstream>
int main(int argc,char**argv){std::vector<unsigned char>b(384*96*4);tj_trophy_popup_configure(argv[1],"fr");tj_trophy_popup_preview(0);assert(tj_trophy_popup_render(b.data(),1536,384,96,0));unsigned n=0;for(unsigned i=3;i<b.size();i+=4)n+=b[i]!=0;assert(n>20000);std::ofstream(argv[2],std::ios::binary).write((char*)b.data(),b.size());assert(!tj_trophy_popup_render(b.data(),1536,384,96,5000));tj_trophy_popup_notify(0,"Real unlock","");assert(tj_trophy_popup_render(b.data(),1536,384,96,5100));}
''',encoding='utf-8')
    exe=tmp_path/'preview.exe'
    subprocess.run([r'C:\Program Files\LLVM\bin\clang++.exe','-std=c++20',str(src),str(ROOT/'src/tj_trophy_popup.cpp'),'-I'+str(ROOT/'src'),'-o',str(exe),'-lgdi32','-lwindowscodecs','-lole32','-luser32'],check=True,capture_output=True)
    subprocess.run([str(exe),str(tmp_path/'catalog.bin'),str(tmp_path/'preview.bgra')],check=True)
    assert (tmp_path/'preview.bgra').stat().st_size==384*96*4
    pixels=(tmp_path/'preview.bgra').read_bytes()
    if icon_kind=='valid': assert pixels[(25*384+25)*4:(25*384+25)*4+4]==bytes([0,0,255,255])
    assert sorted(p.name for p in tmp_path.iterdir())==['catalog.bin','icons','preview.bgra','preview.cpp','preview.exe']
