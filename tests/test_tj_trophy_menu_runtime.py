"""Exercise the real overlay page/input code with a read-only host stub.
Author: matymeatboy. Never boots a game or modifies trophy data.
"""
from pathlib import Path
import importlib.util
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def test_runtime_page():
    spec = importlib.util.spec_from_file_location('tj_build_support', ROOT/'scripts/build_support.py')
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    tools = support.discover_tools()
    env = support.build_environment(tools)
    runtime = ROOT.parent/'ps3recomp'
    source = r'''#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xinput.h>
#include <assert.h>
#include <string.h>
static WORD buttons;
static HWND test_foreground(void) { return (HWND)1; }
static DWORD test_window_pid(HWND h, DWORD* p) { (void)h; *p=GetCurrentProcessId(); return 1; }
static DWORD test_xinput(DWORD i, XINPUT_STATE* st) { memset(st,0,sizeof(*st)); st->Gamepad.wButtons=i?0:buttons; return ERROR_SUCCESS; }
#define GetForegroundWindow test_foreground
#define GetWindowThreadProcessId test_window_pid
#define XInputGetState test_xinput
#include "CELL_PAD_SOURCE"
void vm_write8(unsigned long long a,unsigned char v) {(void)a;(void)v;}
void vm_write16(unsigned long long a,unsigned short v) {(void)a;(void)v;}
void vm_write32(unsigned long long a,unsigned int v) {(void)a;(void)v;}
unsigned char vm_read8(unsigned long long a) {(void)a;return 0;}
LjPromptFamily lj_prompt_choose(const char* s,LjPromptFamily f) {(void)s;return f;}
void lj_gamepads_shutdown(void) {}
int lj_gamepads_poll(LjGamepadState out[4]) {(void)out;return 0;}
int lj_gamepads_rumble(unsigned p,uint16_t a,uint16_t b) {(void)p;(void)a;(void)b;return 0;}
static int opened, keyed, rendered;
static void host_open(void) { opened++; }
static void host_key(int vk,long lp) { (void)lp;keyed=vk; }
static int host_render(void* p,unsigned pitch,unsigned w,unsigned h) { assert(p && pitch==4096 && w==1024 && h==640);rendered++;return 1; }
static int opt_get(void) {return 0;}
static int opt_set(int v) {(void)v;return 1;}
static void press(WORD b) { buttons=0;cellPad_overlay_tick();buttons=b;cellPad_overlay_tick(); }
int main(void) {
    assert(!cellPad_overlay_page_available(2));
    cellPad_overlay_page_key(2); assert(!s_ovl_open);
    assert(cellPad_overlay_register_page(NULL,host_render,host_key,host_open)==-1);
    assert(cellPad_overlay_register_page("Trofeos",host_render,host_key,host_open)==2);
    assert(cellPad_overlay_register_page("Again",host_render,0,0)==-1);
    cellPad_overlay_page_key(2);assert(s_ovl_open && s_ovl_page==2 && opened==1);
    unsigned pixel;assert(cellPad_overlay_render(&pixel,4096,1024,640)==1 && rendered==1);
    cellPad_overlay_key(VK_DOWN,0);assert(keyed==VK_DOWN);
    press(XINPUT_GAMEPAD_DPAD_UP);assert(keyed==VK_UP);
    s_host_state[0].connected=1;s_host_state[0].buttons=0xffff;
    pad_ovl_block_input();assert(s_host_state[0].connected && !s_host_state[0].buttons && s_host_state[0].analog_lx==128);
    press(XINPUT_GAMEPAD_RIGHT_SHOULDER);assert(s_ovl_page==0);
    press(XINPUT_GAMEPAD_RIGHT_SHOULDER);assert(s_ovl_page==2); /* skips absent Options */
    const char* values[]={"a","b"};
    assert(cellPad_overlay_register_option("test",0,values,2,opt_get,opt_set)==0);
    press(XINPUT_GAMEPAD_LEFT_SHOULDER);assert(s_ovl_page==1);
    press(XINPUT_GAMEPAD_LEFT_SHOULDER);assert(s_ovl_page==0);
    press(XINPUT_GAMEPAD_LEFT_SHOULDER);assert(s_ovl_page==2);
    press(XINPUT_GAMEPAD_B);assert(!s_ovl_open && s_ovl_hold);
    s_host_state[0].buttons=1;pad_ovl_block_input();assert(!s_host_state[0].buttons);
    pad_ovl_block_input();assert(!(s_ovl_hold&1));
    cellPad_overlay_page_key(2);cellPad_overlay_key(VK_ESCAPE,0);assert(!s_ovl_open);
    cellPad_overlay_page_key(2);cellPad_overlay_page_key(2);assert(!s_ovl_open);
    press(XINPUT_GAMEPAD_BACK|XINPUT_GAMEPAD_START);assert(s_ovl_open && s_ovl_page==0);
    s_ovl_capture=1;s_ovl_col=0;cellPad_overlay_key(VK_F3,0);assert(s_ovl_capture);
    s_ovl_page_render=0;cellPad_overlay_key(VK_F3,0);assert(!s_ovl_capture && s_pad_keys[s_ovl_row][0]==VK_F3);
    return 0;
}
'''.replace('CELL_PAD_SOURCE', (runtime/'libs/input/cellPad.c').as_posix())
    with tempfile.TemporaryDirectory(prefix='tj-menu-test-') as directory:
        temp=Path(directory); c=temp/'test.c'; c.write_text(source)
        exe=temp/'test.exe'
        args=[str(tools['compiler']),'/nologo','/std:c17','-D_CRT_SECURE_NO_WARNINGS','-I'+str(runtime/'include'),'-I'+str(ROOT/'src'),str(c),'/Fe:'+str(exe),'/Fo:'+str(temp/'test.obj'),'/link','user32.lib','gdi32.lib','xinput.lib']
        result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=120)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr

if __name__=='__main__':
    test_runtime_page()
    print('PASS actual cellPad custom page, navigation, callback, reserved key, and neutral input')
