/* Preserve the last committed save until every callback succeeds.
 * Author: matymeatboy. No game-format assumptions or trophy dependencies. */
#include "tj_savedata_transaction.h"
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <memory>
#include <stdexcept>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

namespace {
namespace fs=std::filesystem;
void no_links(const fs::path& path) {
    for(auto p=fs::absolute(path);!p.empty();) {
        std::error_code ec;const auto status=fs::symlink_status(p,ec);
        if(ec && ec!=std::errc::no_such_file_or_directory)throw fs::filesystem_error("save path",p,ec);
        if(fs::is_symlink(status))throw std::runtime_error("save path is a link");
#ifdef _WIN32
        const auto attr=GetFileAttributesW(p.c_str());
        if(attr!=INVALID_FILE_ATTRIBUTES && (attr&FILE_ATTRIBUTE_REPARSE_POINT))
            throw std::runtime_error("save path is a reparse point");
#endif
        auto parent=p.parent_path();if(parent==p)break;p=parent;
    }
}
void checked_tree(const fs::path& path) {
    no_links(path);
    if(!fs::exists(path))return;
    if(!fs::is_directory(path))throw std::runtime_error("save directory is not a directory");
    for(const auto& entry:fs::recursive_directory_iterator(path)) {
        no_links(entry.path());
        if(!entry.is_regular_file()&&!entry.is_directory())throw std::runtime_error("unsupported save entry");
    }
}
void remove_tree(const fs::path& path) {checked_tree(path);if(fs::exists(path))fs::remove_all(path);}
void durable_tree(const fs::path& path) {
    checked_tree(path);
    for(const auto& entry:fs::recursive_directory_iterator(path))if(entry.is_regular_file()) {
#ifdef _WIN32
        HANDLE h=CreateFileW(entry.path().c_str(),GENERIC_WRITE,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(h==INVALID_HANDLE_VALUE)throw std::runtime_error("cannot flush save file");
        const bool ok=FlushFileBuffers(h)!=0;CloseHandle(h);
        if(!ok)throw std::runtime_error("cannot flush save file");
#else
        int fd=open(entry.path().c_str(),O_RDONLY|O_NOFOLLOW);
        if(fd<0)throw std::runtime_error("cannot flush save file");
        const bool ok=fsync(fd)==0;close(fd);if(!ok)throw std::runtime_error("cannot flush save file");
#endif
    }
}
void rename_directory(const fs::path& from,const fs::path& to) {
#ifdef TJ_SAVEDATA_TRANSACTION_TEST
    extern int tj_savedata_transaction_test_fail_publish;
    if(tj_savedata_transaction_test_fail_publish && from.filename()=="pending")
        throw std::runtime_error("injected publication failure");
#endif
    no_links(from);no_links(to);
#ifdef _WIN32
    if(!MoveFileExW(from.c_str(),to.c_str(),MOVEFILE_WRITE_THROUGH))
        throw std::runtime_error("cannot rename save directory");
#else
    fs::rename(from,to);
#endif
}
struct Transaction {
    fs::path original,work,pending,previous;
    bool writing=false;
#ifdef _WIN32
    HANDLE lock=INVALID_HANDLE_VALUE;
#else
    int lock=-1;
#endif
    ~Transaction() {
#ifdef _WIN32
        if(lock!=INVALID_HANDLE_VALUE)CloseHandle(lock);
#else
        if(lock>=0){flock(lock,LOCK_UN);close(lock);}
#endif
    }
};
thread_local std::unique_ptr<Transaction> active;
}
#ifdef TJ_SAVEDATA_TRANSACTION_TEST
namespace {int tj_savedata_transaction_test_fail_publish=0;}
extern "C" void tj_savedata_transaction_test_publish_failure(int enabled){tj_savedata_transaction_test_fail_publish=enabled;}
#endif

extern "C" int tj_savedata_transaction_begin(const char* directory,int is_save) {
    if(!directory||!*directory||active)return 0;
    try {
        auto tx=std::make_unique<Transaction>();tx->writing=is_save!=0;
        tx->original=fs::absolute(fs::u8path(directory)).lexically_normal();
        checked_tree(tx->original);
        tx->work=tx->original.parent_path()/".savedata-recovery"/tx->original.filename();
        no_links(tx->work);fs::create_directories(tx->work);
        const auto lock_path=tx->work/"transaction.lock";no_links(lock_path);
#ifdef _WIN32
        tx->lock=CreateFileW(lock_path.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(tx->lock==INVALID_HANDLE_VALUE)return 0;
#else
        tx->lock=open(lock_path.c_str(),O_CREAT|O_RDWR|O_NOFOLLOW,0600);
        if(tx->lock<0||flock(tx->lock,LOCK_EX|LOCK_NB))return 0;
#endif
        tx->pending=tx->work/"pending";tx->previous=tx->work/"previous";
        checked_tree(tx->previous);checked_tree(tx->pending);
        // A previous process may have stopped between the two directory renames.
        // Restore the committed generation before discarding an uncommitted stage.
        if(!fs::exists(tx->original)&&fs::exists(tx->previous))
            rename_directory(tx->previous,tx->original);
        remove_tree(tx->pending);
        if(tx->writing&&fs::exists(tx->original)) {
            fs::create_directory(tx->pending);
            fs::copy(tx->original,tx->pending,fs::copy_options::recursive);
            checked_tree(tx->pending);
        }
        // For a new slot pending remains absent: isNewData must stay true.
        active=std::move(tx);return 1;
    }catch(const std::exception& e) {
        std::fprintf(stderr,"[cellSaveData] transaction preparation failed: %s\n",e.what());return 0;
    }
}
extern "C" int tj_savedata_transaction_route(char* path,size_t capacity) {
    if(!path||!capacity)return 0;
    if(!active||!active->writing)return 1;
    try {
        if(fs::absolute(fs::u8path(path)).lexically_normal()!=active->original)return 1;
        const auto stage=active->pending.u8string();
        if(stage.size()>=capacity)return 0;
        std::memcpy(path,stage.c_str(),stage.size()+1);return 1;
    }catch(...){return 0;}
}
extern "C" int tj_savedata_transaction_finish(int success) {
    if(!active)return 0;
    auto tx=std::move(active);
    bool moved_original=false;
    if(!tx->writing)return 1;
    try {
        if(!success){remove_tree(tx->pending);return 1;}
        if(!fs::exists(tx->pending))return 1; // callback elected to save nothing
        durable_tree(tx->pending);
        remove_tree(tx->previous);
        if(fs::exists(tx->original)) {
            checked_tree(tx->original);rename_directory(tx->original,tx->previous);moved_original=true;
        }
        rename_directory(tx->pending,tx->original);
        // Keep exactly one prior generation, outside the game's manual slots.
        return 1;
    }catch(const std::exception& e) {
        std::fprintf(stderr,"[cellSaveData] transaction commit failed: %s\n",e.what());
        try {
            if(moved_original&&!fs::exists(tx->original)&&fs::exists(tx->previous))
                rename_directory(tx->previous,tx->original);
            remove_tree(tx->pending);
        }catch(...) {
            std::fprintf(stderr,"[cellSaveData] previous save retained in .savedata-recovery; retry restores it\n");
        }
        return 0;
    }
}

extern "C" int tj_savedata_transaction_delete(const char* directory) {
    if(!tj_savedata_transaction_begin(directory,0))return 0;
    auto tx=std::move(active);
    try {
        // Explicit deletion invalidates recovery FIRST, under the same lock.
        // Otherwise the next load would resurrect a deliberately deleted slot.
        remove_tree(tx->previous);
        remove_tree(tx->original);
        return 1;
    }catch(const std::exception& e) {
        std::fprintf(stderr,"[cellSaveData] transaction delete failed: %s\n",e.what());return 0;
    }
}

extern "C" int tj_savedata_transaction_recover_root(const char* directory) {
    if(!directory||!*directory)return 0;
    try {
        const auto root=fs::absolute(fs::u8path(directory)).lexically_normal();
        const auto recovery=root/".savedata-recovery";no_links(recovery);
        if(!fs::exists(recovery))return 1;
        for(const auto& entry:fs::directory_iterator(recovery)) {
            no_links(entry.path());if(!entry.is_directory())return 0;
            const auto original=root/entry.path().filename();no_links(original);
            const auto previous=entry.path()/"previous";no_links(previous);
            if(!fs::exists(original)&&fs::exists(previous)) {
                const auto utf8=original.u8string();
                const std::string bytes(reinterpret_cast<const char*>(utf8.data()),utf8.size());
                if(!tj_savedata_transaction_begin(bytes.c_str(),0))return 0;
                if(!tj_savedata_transaction_finish(1))return 0;
            }
        }
        return 1;
    }catch(const std::exception& e) {
        std::fprintf(stderr,"[cellSaveData] recovery before enumeration failed: %s\n",e.what());return 0;
    }
}
