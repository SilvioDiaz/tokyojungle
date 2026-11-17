"""Exercise original launcher's actual INI/environment helpers without a UI."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_prompt_settings_roundtrip():
    source = '#include "' + (ROOT/'tools/launcher/launcher.c').as_posix() + '"\n' + r'''
#include <assert.h>
int main(int argc,char** argv) {
 assert(argc==3);
 MultiByteToWideChar(CP_UTF8,0,argv[1],-1,g_ini,MAXP);
 load_settings();assert(g_settings.prompts==0);
 assert(prompt_setting_index(L"invalid")==0);
 for(int i=0;i<5;++i) {
   g_settings.prompts=i;save_settings();g_settings.prompts=-1;load_settings();
   assert(g_settings.prompts==i);configure_prompt_environment();
   wchar_t value[40];
   GetEnvironmentVariableW(L"LAJUNGLA_PROMPTS",value,40);
   assert(!wcscmp(value,prompt_values[i]));
   GetEnvironmentVariableW(L"TJ_PROMPTS",value,40);
   assert(!wcscmp(value,i==0?L"0":L"1"));
 }
 wchar_t command[4096];
 wchar_t single[] = L"C:\\a & b\\one's.pkg\0";
 assert(content_install_command(command,4096,L"C:\\tool.ps1",L"C:\\root $dir",single,L"C:\\RAP's"));
 assert(wcsstr(command,L"'C:\\a & b\\one''s.pkg'"));
 assert(wcsstr(command,L" -Root 'C:\\root $dir'"));
 assert(wcsstr(command,L" -Licenses 'C:\\RAP''s'"));
 wchar_t multi[] = L"C:\\packages\0base.pkg\0dlc.pkg\0";
 assert(content_install_command(command,4096,L"C:\\tool.ps1",L"C:\\root",multi,L"C:\\licenses"));
 assert(wcsstr(command,L"@('C:\\packages\\base.pkg','C:\\packages\\dlc.pkg')"));
 assert(!content_install_command(command,16,L"C:\\tool.ps1",L"C:\\root",multi,L"C:\\licenses"));
 assert(!content_install_command(command,4096,L"C:\\bad\"tool.ps1",L"C:\\root",multi,L"C:\\licenses"));
 wchar_t wrapper[MAXP],root[MAXP];
 MultiByteToWideChar(CP_UTF8,0,argv[2],-1,wrapper,MAXP);
 wcscpy(root,g_ini);wchar_t* slash=wcsrchr(root,L'\\');assert(slash);*slash=0;
 assert(content_install_command(command,4096,wrapper,root,multi,L"C:\\RAP's & files"));
 STARTUPINFOW si={sizeof si};PROCESS_INFORMATION pi={0};
 assert(CreateProcessW(NULL,command,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,NULL,&si,&pi));
 assert(WaitForSingleObject(pi.hProcess,30000)==WAIT_OBJECT_0);
 DWORD code=1;GetExitCodeProcess(pi.hProcess,&code);assert(code==0);
 CloseHandle(pi.hThread);CloseHandle(pi.hProcess);
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='tj-launcher-prompts-') as directory:
        directory=Path(directory)
        (directory/'test.c').write_text(source,encoding='utf-8')
        subprocess.run(['C:/Program Files/LLVM/bin/clang.exe','-D_CRT_SECURE_NO_WARNINGS',
                        str(directory/'test.c'),str(ROOT/'tools/launcher/trophy_view.c'),
                        str(ROOT/'third_party/cjson/cJSON.c'),'-lcomctl32','-luuid','-luser32','-lgdi32','-lcomdlg32','-lshell32','-lole32','-o',str(directory/'test.exe')],check=True,timeout=180)
        wrapper=directory/"fake installer's.ps1"
        wrapper.write_text("param([string]$Root,[string[]]$Packages,[string]$Licenses)\n[IO.File]::WriteAllLines($Root+'\\received.txt',@($Root,$Licenses)+$Packages)\n")
        subprocess.run([str(directory/'test.exe'),str(directory/'launcher.ini'),str(wrapper)],check=True,timeout=60)
        assert (directory/'received.txt').read_text().splitlines()==[
            str(directory), "C:\\RAP's & files", 'C:\\packages\\base.pkg', 'C:\\packages\\dlc.pkg']
