// Author: matymeatboy. ABI checked against RPCS3 sceNpTrophy.h, not the runtime's
// placeholder host structs. Guest memory is always explicitly big-endian.
#include "lajungla_trophies.h"
#include <array>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <mutex>
#include <regex>
#include <sstream>
#include <string>
#include <vector>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <io.h>
#else
#include <unistd.h>
#endif
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
#include <rl_achievements.h>
#endif

extern "C" uint8_t* vm_base;
extern "C" void ps3_hle_register(uint32_t, const char*, void*);
extern "C" unsigned long long ppu_guest_call_ct(uint32_t, uint32_t,
    uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);

namespace {
namespace fs = std::filesystem;
constexpr uint32_t NOT_INIT=0x80022902, INVALID=0x80022906, CONTEXT=0x8002290a,
    HANDLE=0x80022911, UNREGISTERED=0x80022904, ALREADY=0x80022915,
    PLATINUM=0x80022914, BAD_ID=0x80022920, IO_ERROR=0x8002291a,
    BROKEN=0x8002291e, NO_CONF=0x8002291b, HIDDEN=0x80022913;
constexpr const char* COMM="NPWR01344_00";
struct Trophy { uint32_t id,grade,hidden,pid; std::string name,description,icon; };
struct Context { bool used=false,registered=false,readonly=false; };
std::mutex mutex, sdk_mutex;
std::vector<Trophy> trophies;
std::string title, description;
fs::path state_directory;
std::array<uint64_t,128> timestamps{};
std::array<uint64_t,128> view_timestamps{};
bool view_cached=false,view_valid=false;
std::array<Context,4> contexts{};
std::array<bool,4> handles{};
bool initialized=false,configured=false,loaded=false;
bool sdk_started=false; // protected exclusively by sdk_mutex
lajungla_trophy_notify_fn notification=nullptr;

bool memory(uint32_t address, uint32_t length, bool write=false) {
    if (!vm_base || !address || !length || uint64_t(address)+length > 0x100000000ull) return false;
#ifdef LAJUNGLA_TROPHY_TEST_MEMORY_SIZE
    (void)write;
    return uint64_t(address)+length <= LAJUNGLA_TROPHY_TEST_MEMORY_SIZE;
#else
    const uint64_t end=uint64_t(address)+length;
    if (!((address>=0x10000 && end<=0x10010000) || (address>=0xd0000000 && end<=0xe0000000))) return false;
#ifdef _WIN32
    uintptr_t current=reinterpret_cast<uintptr_t>(vm_base+address), limit=current+length;
    while(current<limit) {
        MEMORY_BASIC_INFORMATION info{};
        if (!VirtualQuery(reinterpret_cast<void*>(current), &info, sizeof(info)) || info.State!=MEM_COMMIT ||
            (info.Protect&(PAGE_GUARD|PAGE_NOACCESS))) return false;
        const DWORD protection=info.Protect&0xff;
        if (write && protection!=PAGE_READWRITE && protection!=PAGE_WRITECOPY &&
            protection!=PAGE_EXECUTE_READWRITE && protection!=PAGE_EXECUTE_WRITECOPY) return false;
        uintptr_t next=reinterpret_cast<uintptr_t>(info.BaseAddress)+info.RegionSize;
        if(next<=current) return false;
        current=next;
    }
#else
    (void)write;
#endif
    return true;
#endif
}
uint32_t read32(uint32_t a) { return uint32_t(vm_base[a])<<24|uint32_t(vm_base[a+1])<<16|uint32_t(vm_base[a+2])<<8|vm_base[a+3]; }
void write32(uint32_t a,uint32_t v) { for(unsigned i=0;i<4;i++) vm_base[a+i]=uint8_t(v>>(24-i*8)); }
void write64(uint32_t a,uint64_t v) { write32(a,uint32_t(v>>32));write32(a+4,uint32_t(v)); }
void text(uint32_t a,const std::string& value,size_t capacity) {
    std::memset(vm_base+a,0,capacity);
    std::memcpy(vm_base+a,value.data(),value.size()<capacity?value.size():capacity-1);
}
const Trophy* find(uint32_t id) { for(const auto& t:trophies) if(t.id==id) return &t;return nullptr; }
uint32_t check(uint32_t context,uint32_t handle,bool registered=true) {
    if(!initialized) return NOT_INIT;
    if(context<1 || context>4 || !contexts[context-1].used) return CONTEXT;
    if(handle<1 || handle>4 || !handles[handle-1]) return HANDLE;
    if(registered && !contexts[context-1].registered) return UNREGISTERED;
    return 0;
}

// Own bounded JSON state grammar, containing no private names or keys. Reject
// partial/malformed files instead of manufacturing unlocks from arbitrary text.
bool read_state(std::array<uint64_t,128>& next) {
    next = {};
    const auto path=state_directory/(std::string(COMM)+".json");
    std::error_code ec;
    if(!fs::exists(path,ec)) { return !ec; }
    if(fs::is_symlink(path,ec) || ec || fs::file_size(path,ec)>32768 || ec) return false;
    std::ifstream in(path,std::ios::binary);
    std::string data((std::istreambuf_iterator<char>(in)),{});
    const std::regex outer(R"rx(^\s*\{\s*"format"\s*:\s*1\s*,\s*"communication_id"\s*:\s*"NPWR01344_00"\s*,\s*"trophies"\s*:\s*\[([\s\S]*)\]\s*\}\s*$)rx");
    std::smatch match;
    if(!std::regex_match(data,match,outer)) return false;
    std::string remaining=match[1].str();
    const std::regex item(R"rx(^\s*\{\s*"id"\s*:\s*([0-9]+)\s*,\s*"timestamp"\s*:\s*([0-9]+)\s*\}\s*)rx");
    bool first=true;
    while(remaining.find_first_not_of(" \r\n\t")!=std::string::npos) {
        if(!first) { if(remaining[0]!=',')return false; remaining.erase(0,1); }
        if(!std::regex_search(remaining,match,item)) return false;
        try {
            const auto id=std::stoull(match[1].str()), when=std::stoull(match[2].str());
            if(id>=128 || !find(uint32_t(id)) || next[id] || !when || when>253402300799ull) return false;
            next[id]=when;
        } catch(...) { return false; }
        remaining.erase(0,size_t(match.length()));first=false;
    }
    return true;
}

bool load() {
    if(loaded) return true;
    std::array<uint64_t,128> next{};
    if(!read_state(next)) return false;
    timestamps=next;loaded=true;return true;
}

bool persist(const std::array<uint64_t,128>& next) {
    std::error_code ec;
    fs::create_directories(state_directory,ec);
    if(ec || fs::is_symlink(state_directory,ec) || ec) return false;
    const auto destination=state_directory/(std::string(COMM)+".json");
    const auto temporary=state_directory/(std::string(COMM)+".json.pending");
    if(fs::is_symlink(destination,ec) || fs::is_symlink(temporary,ec)) return false;
    std::ostringstream json;
    json<<"{\"format\":1,\"communication_id\":\""<<COMM<<"\",\"trophies\":[";
    bool first=true;
    for(const auto& trophy:trophies) if(next[trophy.id]) {
        if(!first) json<<',';first=false;
        json<<"{\"id\":"<<trophy.id<<",\"timestamp\":"<<next[trophy.id]<<'}';
    }
    json<<"]}\n";
    const auto data=json.str();
#ifdef _WIN32
    FILE* file=nullptr;_wfopen_s(&file,temporary.c_str(),L"wb");
#else
    FILE* file=std::fopen(temporary.c_str(),"wb");
#endif
    if(!file) return false;
    bool ok=std::fwrite(data.data(),1,data.size(),file)==data.size() && std::fflush(file)==0;
#ifdef _WIN32
    if(ok) ok=_commit(_fileno(file))==0;
#else
    if(ok) ok=fsync(fileno(file))==0;
#endif
    if(std::fclose(file)!=0) ok=false;
#ifdef _WIN32
    if(ok) ok=MoveFileExW(temporary.c_str(),destination.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)!=0;
#else
    if(ok) { fs::rename(temporary,destination,ec);ok=!ec; }
#endif
    if(!ok) fs::remove(temporary,ec);
    return ok;
}

void sdk_save_loaded() {
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    std::lock_guard<std::mutex> guard(sdk_mutex);if(sdk_started)rl_ach_save_loaded();
#endif
}
void emit(const Trophy& trophy) {
    bool quiet=false;
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    { std::lock_guard<std::mutex> guard(sdk_mutex);if(sdk_started){rl_ach_native(trophy.id);quiet=rl_ach_quiet_toasts()!=0;} }
#endif
    std::printf("[TJ] Trofeo desbloqueado: %u (grado %u)\n",trophy.id,trophy.grade);
    lajungla_trophy_notify_fn notify;
    {std::lock_guard<std::mutex> guard(mutex);notify=notification;}
    if(!quiet && notify) notify(trophy.id,trophy.name.c_str(),trophy.description.c_str());
}

int32_t init(uint32_t,uint32_t,uint32_t,uint64_t options) {
    std::lock_guard<std::mutex> guard(mutex);
    if(initialized) return int32_t(0x80022901);
    if(options) return int32_t(INVALID);
    if(!configured) return int32_t(NO_CONF);
    contexts={};handles={};timestamps={};loaded=false;view_cached=false;initialized=true;return 0;
}
int32_t term() { std::lock_guard<std::mutex> guard(mutex);if(!initialized)return int32_t(NOT_INIT);initialized=false;contexts={};handles={};return 0; }
int32_t create_context(uint32_t out,uint32_t comm,uint32_t sign,uint64_t options) {
    std::lock_guard<std::mutex> guard(mutex);
    if(!initialized)return int32_t(NOT_INIT);
    if(!memory(out,4,true)||!memory(comm,12)||!memory(sign,160)||options>1)return int32_t(INVALID);
    if(std::memcmp(vm_base+comm,"NPWR01344",9)||vm_base[comm+9]||vm_base[comm+10])return int32_t(0x80022918);
    for(unsigned i=0;i<4;i++) if(!contexts[i].used) { contexts[i]={true,false,options==1};write32(out,i+1);return 0; }
    return int32_t(0x80022907);
}
int32_t destroy_context(uint32_t id) {
    std::lock_guard<std::mutex> guard(mutex);if(!initialized)return int32_t(NOT_INIT);
    if(id<1||id>4||!contexts[id-1].used)return int32_t(CONTEXT);contexts[id-1]={};return 0;
}
int32_t create_handle(uint32_t out) {
    std::lock_guard<std::mutex> guard(mutex);if(!initialized)return int32_t(NOT_INIT);
    if(!memory(out,4,true))return int32_t(INVALID);
    for(unsigned i=0;i<4;i++)if(!handles[i]) {handles[i]=true;write32(out,i+1);return 0;}return int32_t(0x80022907);
}
int32_t destroy_handle(uint32_t id) {
    std::lock_guard<std::mutex> guard(mutex);if(!initialized)return int32_t(NOT_INIT);
    if(id<1||id>4||!handles[id-1])return int32_t(HANDLE);handles[id-1]=false;return 0;
}
int32_t register_context(uint32_t context,uint32_t handle,uint32_t callback,uint32_t argument,uint64_t options) {
    uint32_t code=0,toc=0,count=0;bool just_loaded=false;
    { std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle,false);if(error)return int32_t(error);
      if(options>1 || !memory(callback,8))return int32_t(INVALID);
      code=read32(callback);toc=read32(callback+4);if(!memory(code,4)||!memory(toc,4))return int32_t(INVALID);
      if(contexts[context-1].registered)return int32_t(0x8002291d);
      just_loaded=!loaded;if(!load())return int32_t(BROKEN);
      contexts[context-1].registered=true;count=uint32_t(trophies.size()); }
    if(just_loaded)sdk_save_loaded(); // Never replay persisted unlocks as live events.
    ppu_guest_call_ct(code,toc,context,3,count,count,argument,0,0,0);return 0;
}
int32_t disk_space(uint32_t context,uint32_t handle,uint32_t out,uint64_t options) {
    std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle,false);if(error)return int32_t(error);
    if(options||!memory(out,8,true))return int32_t(INVALID);write64(out,1024*1024);return 0;
}
int32_t game_info(uint32_t context,uint32_t handle,uint32_t details,uint32_t data) {
    std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle);if(error)return int32_t(error);
    if((!details&&!data)||(details&&!memory(details,1176,true))||(data&&!memory(data,20,true)))return int32_t(INVALID);
    uint32_t totals[5]={},unlocked[5]={};
    for(const auto& t:trophies) {++totals[0];++totals[t.grade];if(timestamps[t.id]){++unlocked[0];++unlocked[t.grade];}}
    if(details) { std::memset(vm_base+details,0,1176);for(unsigned i=0;i<5;i++)write32(details+i*4,totals[i]);text(details+20,title,128);text(details+148,description,1024); }
    if(data)for(unsigned i=0;i<5;i++)write32(data+i*4,unlocked[i]);return 0;
}
int32_t trophy_info(uint32_t context,uint32_t handle,uint32_t id,uint32_t details,uint32_t data) {
    std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle);if(error)return int32_t(error);
    const Trophy* trophy=find(id);if(!trophy)return int32_t(BAD_ID);
    if((!details&&!data)||(details&&!memory(details,1164,true))||(data&&!memory(data,16,true)))return int32_t(INVALID);
    if(trophy->hidden&&!timestamps[id])return int32_t(HIDDEN);
    if(details) {std::memset(vm_base+details,0,1164);write32(details,id);write32(details+4,trophy->grade);text(details+8,trophy->name,128);text(details+136,trophy->description,1024);vm_base[details+1160]=uint8_t(trophy->hidden);}
    if(data) {std::memset(vm_base+data,0,16);write64(data,timestamps[id]?62135596800000000ull+timestamps[id]*1000000ull:0);write32(data+8,id);vm_base[data+12]=timestamps[id]?1:0;}
    return 0;
}
int32_t unlock(uint32_t context,uint32_t handle,uint32_t id,uint32_t platinum_out) {
    Trophy unlocked;
    { std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle);if(error)return int32_t(error);
      if(contexts[context-1].readonly)return int32_t(0x8002290e);
      if(platinum_out&&!memory(platinum_out,4,true))return int32_t(INVALID);
      const auto trophy=find(id);if(!trophy)return int32_t(BAD_ID);
      if(trophy->grade==1)return int32_t(PLATINUM);
      if(timestamps[id])return int32_t(ALREADY);
      auto next=timestamps;const auto now=std::time(nullptr);if(now<=0)return int32_t(IO_ERROR);next[id]=uint64_t(now);
      if(!persist(next))return int32_t(IO_ERROR);
      timestamps=next;if(platinum_out)write32(platinum_out,0xffffffff);unlocked=*trophy; }
    emit(unlocked);return 0;
}
int32_t unlock_state(uint32_t context,uint32_t handle,uint32_t flags,uint32_t count) {
    std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle);if(error)return int32_t(error);
    if(!memory(flags,16,true)||!memory(count,4,true))return int32_t(INVALID);
    uint32_t bits[4]={};for(const auto& t:trophies)if(timestamps[t.id])bits[t.id/32]|=1u<<(t.id%32);
    for(unsigned i=0;i<4;i++)write32(flags+i*4,bits[i]);write32(count,uint32_t(trophies.size()));return 0;
}
int32_t progress(uint32_t context,uint32_t handle,uint32_t out) {
    std::lock_guard<std::mutex> guard(mutex);const auto error=check(context,handle);if(error)return int32_t(error);
    if(!memory(out,4,true))return int32_t(INVALID);uint32_t total=0;for(const auto& t:trophies)if(timestamps[t.id])++total;
    write32(out,uint32_t((total*100+trophies.size()/2)/trophies.size()));return 0;
}
} // namespace

static int configure_trophy_catalog(const char* catalog,const char* directory,bool bridge) {
    std::lock_guard<std::mutex> guard(mutex);if(initialized || !catalog || !directory)return 0;
    try {
        fs::path path=fs::u8path(catalog);if(fs::file_size(path)>1024*1024)return 0;
        std::ifstream file(path,std::ios::binary);std::string bytes((std::istreambuf_iterator<char>(file)),{});size_t pos=8;
        if(bytes.size()<12 || bytes.compare(0,8,std::string("LJTRP01\0",8)))return 0;
        auto integer=[&]() {if(pos+4>bytes.size())throw 1;uint32_t v=0;for(int i=0;i<4;i++)v=v<<8|uint8_t(bytes[pos++]);return v;};
        auto string=[&](size_t max) {const auto n=integer();if(n>=max||n>bytes.size()-pos)throw 1;auto value=bytes.substr(pos,n);pos+=n;if(value.find('\0')!=std::string::npos)throw 1;return value;};
        const auto count=integer();if(count!=13 || string(32)!=COMM)return 0;
        const auto new_title=string(128),new_description=string(1024);std::vector<Trophy> next;
        for(uint32_t i=0;i<count;i++) {
            Trophy t{};t.id=integer();t.grade=integer();t.hidden=integer();t.pid=integer();
            if(t.id!=i || t.grade!=(i==0?2u:i<4?3u:4u) || t.hidden>1 || t.pid!=0xffffffff)throw 1;
            t.name=string(128);t.description=string(1024);t.icon=string(128);next.push_back(t);
        }
        if(pos!=bytes.size())return 0;
        trophies=std::move(next);title=new_title;description=new_description;state_directory=fs::u8path(directory);configured=true;loaded=false;view_cached=false;
    }catch(...) {return 0;}
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    if(bridge) {
        std::lock_guard<std::mutex> bridge_guard(sdk_mutex);
        if(sdk_started)rl_ach_shutdown();
        rl_ach_set_info("tokyojungle","0.1.0");
        rl_ach_init("ps3",nullptr,nullptr);sdk_started=true;
        for(const auto& trophy:trophies)
            rl_ach_native_define(trophy.id,trophy.name.c_str(),trophy.description.c_str(),
                                 trophy.grade==2?25:trophy.grade==3?10:5);
    }
#endif
    return 1;
}
extern "C" int lajungla_trophies_configure(const char* catalog,const char* directory) {
    return configure_trophy_catalog(catalog,directory,true);
}
extern "C" int lajungla_trophies_configure_view(const char* catalog,const char* directory) {
    return configure_trophy_catalog(catalog,directory,false);
}
extern "C" int lajungla_trophies_snapshot(lajungla_trophy_view* records,uint32_t capacity) {
    std::lock_guard<std::mutex> guard(mutex);
    if(!configured)return 0;
    if(!records||capacity<13)return -1;
    try {
        // Read into a private copy before guest registration. The browser must
        // not consume the game's first-load SDK notification or alter timestamps.
        auto values=timestamps;
        if(!loaded) {
            if(!view_cached) {view_valid=read_state(view_timestamps);view_cached=true;}
            if(!view_valid)return -1;
            values=view_timestamps;
        }
        for(const auto& trophy:trophies) {
            auto& row=records[trophy.id];row={};
            row.id=trophy.id;row.grade=trophy.grade;row.hidden=trophy.hidden;
            row.timestamp=values[trophy.id];row.unlocked=row.timestamp!=0;
            if(row.hidden&&!row.unlocked)continue;
            std::memcpy(row.name,trophy.name.data(),trophy.name.size());
            std::memcpy(row.description,trophy.description.data(),trophy.description.size());
            std::snprintf(row.icon,sizeof(row.icon),"icons/TROP%03u.PNG",trophy.id);
        }
        return int(trophies.size());
    }catch(...) {return -1;}
}
extern "C" void lajungla_trophies_register() {
#define REG(nid,name,fn) ps3_hle_register(nid,name,reinterpret_cast<void*>(fn))
    REG(0x39567781,"sceNpTrophyInit",init);REG(0xa7fabf4d,"sceNpTrophyTerm",term);
    REG(0xe3bf9a28,"sceNpTrophyCreateContext",create_context);REG(0x3741ecc7,"sceNpTrophyDestroyContext",destroy_context);
    REG(0x1c25470d,"sceNpTrophyCreateHandle",create_handle);REG(0x623cd2dc,"sceNpTrophyDestroyHandle",destroy_handle);
    REG(0x1197b52c,"sceNpTrophyRegisterContext",register_context);REG(0x370136fe,"sceNpTrophyGetRequiredDiskSpace",disk_space);
    REG(0x49d18217,"sceNpTrophyGetGameInfo",game_info);REG(0xfce6d30a,"sceNpTrophyGetTrophyInfo",trophy_info);
    REG(0x8ceedd21,"sceNpTrophyUnlockTrophy",unlock);REG(0xb3ac3478,"sceNpTrophyGetTrophyUnlockState",unlock_state);
    REG(0x079f0e87,"sceNpTrophyGetGameProgress",progress);
#undef REG
}
extern "C" void lajungla_trophies_frame() {
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    std::lock_guard<std::mutex> guard(sdk_mutex);if(sdk_started)rl_ach_frame();
#endif
}
extern "C" void lajungla_trophies_save_loaded() {sdk_save_loaded();}
extern "C" void lajungla_trophies_casual(const char* reason) {
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    std::lock_guard<std::mutex> guard(sdk_mutex);if(sdk_started)rl_ach_casual(reason?reason:"debug");
#else
    (void)reason;
#endif
}
extern "C" void lajungla_trophies_shutdown() {
#ifdef LAJUNGLA_RECOMP_ACHIEVEMENTS
    std::lock_guard<std::mutex> guard(sdk_mutex);if(sdk_started)rl_ach_shutdown();sdk_started=false;
#endif
}
extern "C" void lajungla_trophies_set_notify(lajungla_trophy_notify_fn notify) {std::lock_guard<std::mutex> guard(mutex);notification=notify;}
