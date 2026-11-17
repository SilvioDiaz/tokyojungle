"""Synthetic original-ABI trophies; author: matymeatboy. No game texts/assets."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from lajungla_trophy_catalog import (CatalogError, achievements_set, encode_catalog,
                                    extract_catalog, prepare_catalog)


def catalog():
    return {'format': 1, 'communication_id': 'NPWR01344_00', 'title': 'Synthetic game',
            'description': 'Only fixture text', 'trophies': [
                {'id': i, 'grade': 2 if i == 0 else 3 if i < 4 else 4,
                 'hidden': False, 'pid': -1, 'name': f'Fixture {i}',
                 'description': 'x'*700, 'icon': f'icons/TROP{i:03}.PNG'} for i in range(13)]}


def trp(path, entries):
    header = bytearray(64)
    table = bytearray(len(entries)*64)
    content = bytearray()
    for index, (name, payload) in enumerate(entries):
        record = index*64
        table[record:record+len(name)] = name.encode()
        struct.pack_into('>QQ', table, record+32, 64+len(table)+len(content), len(payload))
        content.extend(payload)
    struct.pack_into('>IIQII', header, 0, 0xdca24d00, 1, 64+len(table)+len(content), len(entries), 64)
    path.write_bytes(header+table+content)
    return path


def xml(ids=(0, 1), grade='G'):
    return ('<trophyconf><title-name>Fixture</title-name>' + ''.join(
        f'<trophy id="{i}" hidden="no" ttype="{grade}" pid="-1"><name>Fixture {i}</name><detail>Condition {i}</detail></trophy>'
        for i in ids) + '</trophyconf>').encode()


def test_private_catalog_preserves_ids_and_gold_id_zero_in_native_set(tmp_path):
    source = trp(tmp_path/'test.trp', [('TROPCONF.SFM', xml()), ('TROP_01.SFM', xml()),
                                     ('TROP000.PNG', b'synthetic icon')])
    data = prepare_catalog(source, tmp_path/'metadata')
    native = json.loads((tmp_path/'metadata/recompachievements.json').read_text())
    assert native['source'] == 'native' and native['console'] == 'ps3'
    assert [t['id'] for t in native['achievements']] == [0, 1]
    assert native['achievements'][0]['native'] == 0
    assert native['achievements'][0]['points'] == 25
    assert (tmp_path/'metadata/catalog.bin').read_bytes() == encode_catalog(data)
    assert (tmp_path/'metadata/icons/TROP000.PNG').read_bytes() == b'synthetic icon'
    assert source.read_bytes().startswith(bytes.fromhex('dca24d00'))


def test_actual_platinum_grade_omitted_without_changing_original_ids():
    data = catalog()
    data['trophies'][0]['grade'] = 1
    assert [t['id'] for t in achievements_set(data)['achievements']] == list(range(1, 13))


@pytest.mark.parametrize('entries', [
    [('TROPCONF.SFM', xml()), ('TROP_01.SFM', xml((1, 2)))],
    [('TROPCONF.SFM', xml()), ('TROP_01.SFM', xml(grade='B'))],
    [('TROPCONF.SFM', xml((0, 0)))],
    [('TROPCONF.SFM', b'<!DOCTYPE x [<!ENTITY a "b">]><trophyconf/>')],
    [('../escape', b'bad'), ('TROPCONF.SFM', xml())],
])
def test_rejects_corrupt_catalog_or_unsafe_archive(tmp_path, entries):
    with pytest.raises(CatalogError):
        extract_catalog(trp(tmp_path/'bad.trp', entries))


HARNESS = r'''
#include "lajungla_trophies.h"
#include <array>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <cstdint>
static std::array<uint8_t,1048576> memory{};
extern "C" {uint8_t* vm_base=memory.data();}
static std::map<uint32_t,void*> functions;
static unsigned native_events,notifications,loads,frames,casuals;
static bool quiet_toasts=false;
extern "C" void ps3_hle_register(uint32_t id,const char*,void* fn){functions[id]=fn;}
extern "C" unsigned long long ppu_guest_call_ct(uint32_t code,uint32_t toc,
 uint64_t ctx,uint64_t status,uint64_t complete,uint64_t total,uint64_t arg,uint64_t,uint64_t,uint64_t) {
 assert(code==0x10300&&toc==0x10400&&ctx==1&&status==3&&complete==13&&total==13&&arg==77);return 0;
}
extern "C" void rl_ach_set_info(const char* id,const char*){assert(std::string(id)=="tokyojungle");}
extern "C" int rl_ach_init(const char* console,void*,void*){assert(std::string(console)=="ps3");return 1;}
static unsigned definitions=0;
extern "C" void rl_ach_native_define(uint32_t id,const char* title,const char*,uint32_t points){assert(id==definitions&&std::string(title)=="Fixture "+std::to_string(id));assert(points==(id==0?25u:id<4?10u:5u));++definitions;}
extern "C" void rl_ach_native(uint32_t id){assert(id<=1);++native_events;}
extern "C" int rl_ach_quiet_toasts(){return quiet_toasts;}
extern "C" void rl_ach_frame(){++frames;}
extern "C" void rl_ach_save_loaded(){++loads;}
extern "C" void rl_ach_casual(const char*){++casuals;}
extern "C" void rl_ach_shutdown(){}
static void notify(uint32_t id,const char* name,const char*){assert(id<=1&&std::string(name)=="Fixture "+std::to_string(id));++notifications;}
static uint32_t rd(uint32_t a){return uint32_t(memory[a])<<24|uint32_t(memory[a+1])<<16|uint32_t(memory[a+2])<<8|memory[a+3];}
static void wr(uint32_t a,uint32_t v){for(int i=0;i<4;i++)memory[a+i]=uint8_t(v>>(24-i*8));}
template<class... Args> uint32_t call(uint32_t nid,Args... args){return uint32_t(reinterpret_cast<int32_t(*)(Args...)>(functions.at(nid))(args...));}
static void start(uint32_t expected=0){
 assert(call(0x39567781,uint32_t(0),uint32_t(0),uint32_t(0),uint64_t(0))==0);
 std::memcpy(memory.data()+0x10000,"NPWR01344",9);
 assert(call(0xe3bf9a28,uint32_t(0x10100),uint32_t(0x10000),uint32_t(0x10500),uint64_t(0))==0);
 assert(rd(0x10100)==1);
 assert(call(0x1c25470d,uint32_t(0x10104))==0&&rd(0x10104)==1);
 wr(0x10200,0x10300);wr(0x10204,0x10400);
 assert(call(0x1197b52c,uint32_t(1),uint32_t(1),uint32_t(0x10200),uint32_t(77),uint64_t(0))==expected);
}
int main(int argc,char** argv){
 assert(argc==3||argc==4);namespace fs=std::filesystem;
 if(argc==4&&std::string(argv[3])=="badcatalog"){assert(lajungla_trophies_configure(argv[1],argv[2])==0);return 0;}
 assert(lajungla_trophies_configure(argv[1],argv[2])==1);
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
 assert(definitions==13);
#endif
 lajungla_trophies_register();assert(functions.size()==13);lajungla_trophies_set_notify(notify);
 if(argc==4){start(0x8002291e);assert(!notifications&&!native_events&&!loads);return 0;}start();
 assert(call(0x49d18217,uint32_t(1),uint32_t(1),uint32_t(1048570),uint32_t(0))==0x80022906);
 memory[0x20000-1]=0xAB;memory[0x20000+1176]=0xCD;
 assert(call(0x49d18217,uint32_t(1),uint32_t(1),uint32_t(0x20000),uint32_t(0x21000))==0);
 assert(rd(0x20000)==13&&rd(0x20004)==0&&rd(0x20008)==1&&rd(0x2000c)==3&&rd(0x20010)==9);
 assert(memory[0x1ffff]==0xAB&&memory[0x20000+1176]==0xCD);
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(13),uint32_t(0x22000))==0x80022920);
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(1048575))==0x80022906);
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(0x22000))==0);
 assert(rd(0x22000)==0xffffffff&&notifications==1);
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(0x22000))==0x80022915);
 assert(notifications==1);
 memory[0x23000+1164]=0xEF;
 assert(call(0xfce6d30a,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(0x23000),uint32_t(0x24000))==0);
 assert(rd(0x23000)==0&&rd(0x23004)==2&&memory[0x23000+136+699]=='x'&&memory[0x23000+1164]==0xEF);
 uint64_t tick=(uint64_t(rd(0x24000))<<32)|rd(0x24004);assert(tick>62135596800000000ull&&memory[0x2400c]==1);
 assert(call(0xb3ac3478,uint32_t(1),uint32_t(1),uint32_t(0x25000),uint32_t(0x25010))==0);
 assert(rd(0x25000)==1&&rd(0x25010)==13);
 assert(call(0x079f0e87,uint32_t(1),uint32_t(1),uint32_t(0x25014))==0&&rd(0x25014)==8);
 assert(call(0xa7fabf4d)==0);start();assert(notifications==1);
 assert(call(0xfce6d30a,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(0),uint32_t(0x24000))==0);
 assert(((uint64_t(rd(0x24000))<<32)|rd(0x24004))==tick);
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(0),uint32_t(0x22000))==0x80022915);
 fs::path directory=fs::u8path(argv[2]);auto backup=directory;backup+=".old";
 fs::rename(directory,backup);{std::ofstream block(directory);block<<"not a directory";}
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(1),uint32_t(0x22000))==0x8002291a);
 assert(call(0xb3ac3478,uint32_t(1),uint32_t(1),uint32_t(0x25000),uint32_t(0x25010))==0&&rd(0x25000)==1);
 assert(notifications==1);fs::remove(directory);fs::rename(backup,directory);
#ifdef TEST_QUIET_TOASTS
 quiet_toasts=true;
#endif
 assert(call(0x8ceedd21,uint32_t(1),uint32_t(1),uint32_t(1),uint32_t(0))==0);
 assert(notifications==(quiet_toasts?1u:2u));
 lajungla_trophies_frame();lajungla_trophies_save_loaded();lajungla_trophies_casual("debug");lajungla_trophies_shutdown();
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
 assert(native_events==2&&loads==3&&frames==1&&casuals==1);
#else
 assert(native_events==0&&loads==0&&frames==0&&casuals==0);
#endif
 puts("Original trophy ABI, exact counts, atomic state, duplicate/load suppression: passed");return 0;
}
'''


@pytest.mark.parametrize('view_only,bad_state', [(False,False), (True,False), (True,True)])
def test_host_snapshot_is_readonly_and_masks_secret_trophies(tmp_path, view_only, bad_state):
    data = catalog()
    data['trophies'][12]['hidden'] = True
    binary = tmp_path/'catalog.bin'
    binary.write_bytes(encode_catalog(data))
    state = tmp_path/'state'
    state.mkdir()
    path = state/'NPWR01344_00.json'
    payload = b'broken' if bad_state else json.dumps({'format': 1, 'communication_id': 'NPWR01344_00',
        'trophies': [{'id': 0, 'timestamp': 1800000000}]}).encode()
    path.write_bytes(payload)
    source = HARNESS.split('int main(int argc,char** argv){')[0] + r'''
int main(int argc,char** argv){
 assert(argc==4);lajungla_trophy_view rows[13]{};
 assert(lajungla_trophies_snapshot(rows,13)==0);
 const bool view=argv[3][0]=='v',broken=argv[3][1]=='b';
 assert((view?lajungla_trophies_configure_view(argv[1],argv[2]):lajungla_trophies_configure(argv[1],argv[2]))==1);
 assert(lajungla_trophies_snapshot(rows,12)==-1);
 assert(lajungla_trophies_snapshot(nullptr,13)==-1);
 int result=lajungla_trophies_snapshot(rows,13);
 if(broken){assert(result==-1);return 0;}
 assert(result==13&&rows[0].unlocked==1&&rows[0].timestamp==1800000000&&rows[0].grade==2);
 assert(rows[1].unlocked==0&&rows[1].timestamp==0&&rows[1].grade==3);
 assert(rows[12].hidden&&!rows[12].unlocked&&!rows[12].name[0]&&!rows[12].description[0]&&!rows[12].icon[0]);
 assert(!strcmp(rows[0].icon,"icons/TROP000.PNG"));
 assert(!native_events&&!notifications&&!loads);
 auto original=std::filesystem::path(argv[2])/"NPWR01344_00.json";
 auto held=original;held+=".held";std::filesystem::rename(original,held);
 assert(lajungla_trophies_snapshot(rows,13)==13&&rows[0].unlocked==1);
 std::filesystem::rename(held,original);
 if(view){assert(definitions==0);}else{lajungla_trophies_register();start();assert(loads==1&&definitions==13);}
 assert(lajungla_trophies_snapshot(rows,13)==13&&!native_events&&!notifications);
 lajungla_trophies_shutdown();return 0;
}
'''
    (tmp_path/'rl_achievements.h').write_text('''#pragma once
#include <stdint.h>
extern "C" {void rl_ach_set_info(const char*,const char*);int rl_ach_init(const char*,void*,void*);
void rl_ach_native_define(uint32_t,const char*,const char*,uint32_t);void rl_ach_native(uint32_t);
int rl_ach_quiet_toasts();void rl_ach_frame();void rl_ach_save_loaded();void rl_ach_casual(const char*);void rl_ach_shutdown();}
''')
    cpp, exe = tmp_path/'view.cpp', tmp_path/'view.exe'
    cpp.write_text(source)
    compiler = shutil.which('clang++') or r'C:\Program Files\LLVM\bin\clang++.exe'
    subprocess.run([compiler, '-std=c++20', '-O0', '-DLAJUNGLA_TROPHY_TEST_MEMORY_SIZE=1048576',
                    '-DLAJUNGLA_RECOMP_ACHIEVEMENTS=1', '-I', str(ROOT/'src'), '-I', str(tmp_path),
                    str(cpp), str(ROOT/'src/lajungla_trophies.cpp'), '-o', str(exe)],
                   check=True, capture_output=True, text=True)
    mode = ('v' if view_only else 'g') + ('b' if bad_state else 'o')
    subprocess.run([str(exe), str(binary), str(state), mode], check=True)
    assert path.read_bytes() == payload
    assert list(state.iterdir()) == [path]


@pytest.mark.parametrize('sdk,quiet', [(False,False), (True,False), (True,True)])
def test_actual_cpp_hle_abi_persistence_and_optional_sdk(tmp_path, sdk, quiet):
    binary = tmp_path/'catalog.bin'
    binary.write_bytes(encode_catalog(catalog()))
    harness = tmp_path/'harness.cpp'
    harness.write_text(HARNESS)
    (tmp_path/'rl_achievements.h').write_text('''#pragma once
#include <stdint.h>
extern "C" {void rl_ach_set_info(const char*,const char*);int rl_ach_init(const char*,void*,void*);
void rl_ach_native_define(uint32_t,const char*,const char*,uint32_t);
void rl_ach_native(uint32_t);int rl_ach_quiet_toasts();void rl_ach_frame();
void rl_ach_save_loaded();void rl_ach_casual(const char*);void rl_ach_shutdown();}
''')
    compiler = shutil.which('clang++') or r'C:\Program Files\LLVM\bin\clang++.exe'
    exe = tmp_path/'trophies.exe'
    command = [compiler, '-std=c++17', '-O0', '-DLAJUNGLA_TROPHY_TEST_MEMORY_SIZE=1048576',
               '-I', str(ROOT/'src'), '-I', str(tmp_path), str(harness), str(ROOT/'src/lajungla_trophies.cpp'), '-o', str(exe)]
    if sdk:
        command.append('-DLAJUNGLA_RECOMP_ACHIEVEMENTS=1')
    if quiet:
        command.append('-DTEST_QUIET_TOASTS=1')
    subprocess.run(command, check=True, capture_output=True, text=True)
    subprocess.run([str(exe), str(binary), str(tmp_path/'state')], check=True)
    persisted = json.loads((tmp_path/'state/NPWR01344_00.json').read_text())
    assert persisted['communication_id'] == 'NPWR01344_00'
    assert [t['id'] for t in persisted['trophies']] == [0, 1]
    assert persisted['trophies'][0]['timestamp'] > 1700000000
    (tmp_path/'state/NPWR01344_00.json').write_text('{"format":1,"communication_id":"NPWR01344_00","trophies":[{"id":99,"timestamp":1800000000}]}')
    subprocess.run([str(exe), str(binary), str(tmp_path/'state'), 'badstate'], check=True)
    invalid = bytearray(binary.read_bytes())
    struct.pack_into('>I', invalid, 8, 128)
    binary.write_bytes(invalid)
    subprocess.run([str(exe), str(binary), str(tmp_path/'state'), 'badcatalog'], check=True)


def test_actual_savedata_patch_reports_only_successful_nonempty_loads(tmp_path):
    runtime = ROOT.parent/'ps3recomp/libs/system/cellSaveData.c'
    production = runtime.read_text(encoding='utf-8')
    if 'LJ_SAVE_BEGIN' not in production:
        destination = tmp_path/'libs/system/cellSaveData.c'
        destination.parent.mkdir(parents=True)
        destination.write_text(production, encoding='utf-8')
        subprocess.run(['git', 'apply', str(ROOT/'patches/ps3recomp/lajungla-trophies.patch')], cwd=tmp_path, check=True)
        production = destination.read_text(encoding='utf-8')
    macros = production[production.index('/* LaJungla game-only'):production.index("/* glibc's")]
    def definition(signature):
        start = production.index(signature)
        while production.index(';', start) < production.index('{', start):
            start = production.index(signature, start+len(signature))
        brace = production.index('{', start)
        end, depth = brace+1, 1
        while depth:
            depth += (production[end] == '{') - (production[end] == '}')
            end += 1
        return production[start:end]
    read_start = production.index('    case CELL_SAVEDATA_FILEOP_READ: {')
    read_end = production.index('    case CELL_SAVEDATA_FILEOP_WRITE:', read_start)
    read_body = production[read_start:read_end].replace('    case CELL_SAVEDATA_FILEOP_READ:', '', 1)
    source = '''#include <stdio.h>
#include <stdint.h>
#include <assert.h>
typedef int32_t s32; typedef unsigned CellSaveDataSetBuf;
typedef void* CellSaveDataStatCallback;typedef void* CellSaveDataFileCallback;
#define CELL_OK 0
/* Atomic savedata behavior is covered independently; this fixture isolates trophy reporting. */
#define TJ_ATOMIC_BEGIN(dir,save) ((void)0)
#define TJ_ATOMIC_FINISH(result) ((void)0)
static int notifications,s_savedata_busy,force_failure;
void lajungla_trophies_save_loaded(void){++notifications;}
''' + macros + '''
typedef struct{unsigned fileOffset,fileSize,fileBufSize;void* fileBuf;} Set;
static int read_file(const char* file_path,const Set* set)
''' + read_body + '''
static unsigned requested_size=1;
static s32 savedata_execute_impl(const char* path,int is_save,CellSaveDataSetBuf* b,
CellSaveDataStatCallback s,CellSaveDataFileCallback f,void* u){
 (void)is_save;(void)b;(void)s;(void)f;(void)u;char byte;
 Set set={0,requested_size,1,&byte};int result=read_file(path,&set);
 return result<0||force_failure?-1:0;
}
static s32 savedata_execute_guest_auto_impl(const char* p,int save,CellSaveDataSetBuf* b,
CellSaveDataStatCallback s,CellSaveDataFileCallback f,void* u){return savedata_execute_impl(p,save,b,s,f,u);}
''' + definition('static s32 savedata_execute(') + '\n' + definition('static s32 savedata_execute_guest_auto(') + '''
int main(int argc,char** argv){assert(argc==2);FILE* out=fopen(argv[1],"wb");assert(out);fputs("fixture",out);fclose(out);
 assert(savedata_execute(argv[1],0,0,0,0,0)==0&&notifications==1);
 assert(savedata_execute(argv[1],1,0,0,0,0)==0&&notifications==1);
 requested_size=0;assert(savedata_execute(argv[1],0,0,0,0,0)==0&&notifications==1);
 requested_size=1;force_failure=1;assert(savedata_execute(argv[1],0,0,0,0,0)==-1&&notifications==1);
 force_failure=0;assert(savedata_execute_guest_auto(argv[1],0,0,0,0,0)==0&&notifications==2);
 assert(savedata_execute("missing.fixture",0,0,0,0,0)==-1&&notifications==2);
 assert(!s_savedata_busy);return 0;}
'''
    c = tmp_path/'savedata.c'
    c.write_text(source)
    compiler = shutil.which('clang') or r'C:\Program Files\LLVM\bin\clang.exe'
    exe = tmp_path/'savedata.exe'
    subprocess.run([compiler, '-std=c11', '-DLAJUNGLA_TROPHIES=1', str(c), '-o', str(exe)], check=True, capture_output=True, text=True)
    subprocess.run([str(exe), str(tmp_path/'save.fixture')], check=True, cwd=tmp_path)
