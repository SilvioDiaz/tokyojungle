"""Read-only trophy browser native regression. Author: matymeatboy."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_readonly_browser(tmp_path):
    assert (ROOT/'src/tj_trophy_menu.cpp').exists(), 'trophy browser missing'
    source=r'''
#include "tj_trophy_menu.cpp"
#include <cassert>
int status=13, extra=0;
extern "C" int lajungla_trophies_snapshot(lajungla_trophy_view* out,uint32_t capacity){
 if(status!=13)return status;
 assert(capacity>=13);
 for(int i=0;i<13;i++){out[i]={};out[i].id=i;out[i].grade=i==0?2:i<4?3:4;out[i].hidden=i==12;strcpy_s(out[i].name,"SECRET NAME");strcpy_s(out[i].description,"SECRET DESCRIPTION");}
 out[0].unlocked=1;out[1].unlocked=extra;return 13;
}
int main(){
 std::vector<unsigned char>b(640*480*4+16,0xCD);
 tj_trophy_menu_configure("missing/catalog.bin","es");tj_trophy_menu_open();
 assert(tj_trophy_menu_render(b.data(),2560,640,480));
 assert(earned==1);assert(selected==0);
 assert(gradeColor(rows[0])==RGB(238,192,66));assert(gradeColor(rows[1])==RGB(128,128,128));
 assert(!tj_trophy_menu_render(b.data(),2560,640,480));
 extra=1;assert(tj_trophy_menu_render(b.data(),2560,640,480));assert(earned==2);
 assert(gradeColor(rows[1])==RGB(211,222,235));
 assert(b[(132*640+47)*4]==66);assert(b[(132*640+47)*4+2]==238);
 assert(b[(200*640+47)*4]==128);assert(b[(200*640+47)*4+2]==128);
 tj_trophy_menu_key(VK_END,0);assert(selected==12);assert(displayName(rows[12])==L"Trofeo secreto");
 tj_trophy_menu_key(VK_DOWN,0);assert(selected==12);tj_trophy_menu_key(VK_HOME,0);assert(selected==0);
 for(unsigned i=640*480*4;i<b.size();i++)assert(b[i]==0xCD);
 status=-1;assert(tj_trophy_menu_render(b.data(),2560,640,480));assert(snapshotStatus==-1);
 status=0;assert(tj_trophy_menu_render(b.data(),2560,640,480));assert(snapshotStatus==0);
 assert(!tj_trophy_menu_render(b.data(),1,640,480));
}
'''
    src=tmp_path/'menu.cpp';src.write_text(source,encoding='utf-8')
    exe=tmp_path/'menu.exe'
    p=subprocess.run([r'C:\Program Files\LLVM\bin\clang++.exe','-std=c++20',str(src),'-I'+str(ROOT/'src'),'-o',str(exe),'-lgdi32','-lwindowscodecs','-lole32','-luser32'],capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
    subprocess.run([str(exe)],check=True,cwd=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir())==['menu.cpp','menu.exe']




def test_badges_are_bounded_and_gray_when_locked(tmp_path):
    import struct, zlib
    def chunk(t,b): return struct.pack('>I',len(b))+t+b+struct.pack('>I',zlib.crc32(t+b))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\xff\0\0\xff'))+chunk(b'IEND',b'')
    icons=tmp_path/'icons';icons.mkdir()
    (icons/'TROP000.PNG').write_bytes(png)
    (icons/'TROP001.PNG').write_bytes(b'X'*(1024*1024+1))
    source=r'''
#include "tj_trophy_menu.cpp"
#include <cassert>
int lockState=0;
extern "C" int lajungla_trophies_snapshot(lajungla_trophy_view* o,uint32_t){for(int i=0;i<13;i++){o[i]={};o[i].id=i;o[i].grade=i==0?2:i<4?3:4;o[i].unlocked=lockState;}return 13;}
int main(int argc,char**argv){std::vector<unsigned char>b(1024*640*4);tj_trophy_menu_configure(argv[1],"en");tj_trophy_menu_open();assert(tj_trophy_menu_render(b.data(),4096,1024,640));assert(badge.size()==96*96*4);auto*p=&b[(140*1024+610)*4];assert(p[0]==p[1]&&p[1]==p[2]);lockState=1;assert(tj_trophy_menu_render(b.data(),4096,1024,640));p=&b[(140*1024+610)*4];assert(p[0]==0&&p[1]==0&&p[2]==255);tj_trophy_menu_key(VK_DOWN,0);assert(tj_trophy_menu_render(b.data(),4096,1024,640));assert(badge.empty());}
'''
    src=tmp_path/'badge.cpp';src.write_text(source,encoding='utf-8');exe=tmp_path/'badge.exe'
    p=subprocess.run([r'C:\Program Files\LLVM\bin\clang++.exe','-std=c++20',str(src),'-I'+str(ROOT/'src'),'-o',str(exe),'-lgdi32','-lwindowscodecs','-lole32','-luser32'],capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
    before={p.name:p.read_bytes() for p in icons.iterdir()}
    subprocess.run([str(exe),str(tmp_path/'catalog.bin')],check=True,cwd=tmp_path)
    assert before=={p.name:p.read_bytes() for p in icons.iterdir()}
