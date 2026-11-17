/* Read-only viewer for the original game's privately extracted trophy catalog.
 * MIT License, Copyright (c) 2026 matymeatboy. See third_party/cjson/LICENSE for MIT terms.
 * cJSON by Dave Gamble and contributors (MIT); third_party/cjson/LICENSE.
 * No achievement-service SDK/API, game catalog, or game artwork is included.
 */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <commctrl.h>
#include <stdio.h>
#include <stdint.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "trophy_view.h"
#include "../../third_party/cjson/cJSON.h"

#define TROPHIES 13
#define CATALOG_ID "NPWR01344_00"
typedef struct {
    int id,grade,hidden,unlocked;
    uint64_t timestamp;
    wchar_t name[256],description[2048];
} Trophy;
typedef struct {
    Trophy rows[TROPHIES];
    int count,unlocked;
    wchar_t title[256];
    HWND list,detail;
} TrophyModel;

static const wchar_t *display_name(const Trophy *t) {
    return t->hidden&&!t->unlocked?L"Trofeo oculto":t->name;
}
static const wchar_t *display_description(const Trophy *t) {
    return t->hidden&&!t->unlocked?L"Desbloquea este trofeo para ver su descripción.":t->description;
}
static int utf8(const char *src,wchar_t *out,int capacity) {
    return src&&MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,src,-1,out,capacity)>0;
}
static int integer(const cJSON *item,int min,int max,int *out) {
    if(!cJSON_IsNumber(item)||!isfinite(item->valuedouble)||item->valuedouble<min||
       item->valuedouble>max||floor(item->valuedouble)!=item->valuedouble)return 0;
    *out=(int)item->valuedouble;return 1;
}
/* Reject ambiguous duplicate object keys, including nested objects. */
static int unique_keys(const cJSON *node) {
    if(cJSON_IsObject(node)) {
        for(const cJSON *a=node->child;a;a=a->next) {
            for(const cJSON *b=a->next;b;b=b->next)
                if(a->string&&b->string&&!strcmp(a->string,b->string))return 0;
        }
    }
    for(const cJSON *a=node->child;a;a=a->next)if(!unique_keys(a))return 0;
    return 1;
}
static cJSON *document(const char *text) {
    cJSON *doc=cJSON_ParseWithOpts(text,NULL,1);
    if(!doc||!cJSON_IsObject(doc)||!unique_keys(doc)){cJSON_Delete(doc);return NULL;}
    int format=0;
    const cJSON *id=cJSON_GetObjectItemCaseSensitive(doc,"communication_id");
    if(!integer(cJSON_GetObjectItemCaseSensitive(doc,"format"),1,1,&format)||
       !cJSON_IsString(id)||strcmp(id->valuestring,CATALOG_ID)) {
        cJSON_Delete(doc);return NULL;
    }
    return doc;
}
static int parse_model(const char *catalog,const char *state,TrophyModel *model) {
    TrophyModel next={0};
    cJSON *doc=document(catalog),*save=NULL;
    if(!doc)return 0;
    const cJSON *title=cJSON_GetObjectItemCaseSensitive(doc,"title");
    const cJSON *rows=cJSON_GetObjectItemCaseSensitive(doc,"trophies");
    int seen[TROPHIES]={0},ok=cJSON_IsString(title)&&
        utf8(title->valuestring,next.title,_countof(next.title))&&
        cJSON_IsArray(rows)&&cJSON_GetArraySize(rows)==TROPHIES;
    const cJSON *row;
    cJSON_ArrayForEach(row,rows) {
        if(!ok)break;
        int id=0,grade=0;
        const cJSON *hidden=cJSON_GetObjectItemCaseSensitive(row,"hidden");
        const cJSON *name=cJSON_GetObjectItemCaseSensitive(row,"name");
        const cJSON *desc=cJSON_GetObjectItemCaseSensitive(row,"description");
        ok=cJSON_IsObject(row)&&integer(cJSON_GetObjectItemCaseSensitive(row,"id"),0,TROPHIES-1,&id)&&
            integer(cJSON_GetObjectItemCaseSensitive(row,"grade"),1,4,&grade)&&
            cJSON_IsBool(hidden)&&cJSON_IsString(name)&&cJSON_IsString(desc);
        if(!ok||seen[id]){ok=0;break;}
        seen[id]=1;Trophy *t=&next.rows[id];
        t->id=id;t->grade=grade;t->hidden=cJSON_IsTrue(hidden);
        ok=utf8(name->valuestring,t->name,_countof(t->name))&&
            utf8(desc->valuestring,t->description,_countof(t->description));
        next.count++;
    }
    if(ok&&state) {
        save=document(state);ok=save!=NULL;
        const cJSON *unlocks=save?cJSON_GetObjectItemCaseSensitive(save,"trophies"):NULL;
        ok=ok&&cJSON_IsArray(unlocks)&&cJSON_GetArraySize(unlocks)<=TROPHIES;
        cJSON_ArrayForEach(row,unlocks) {
            if(!ok)break;
            int id=0;const cJSON *stamp=cJSON_GetObjectItemCaseSensitive(row,"timestamp");
            ok=cJSON_IsObject(row)&&integer(cJSON_GetObjectItemCaseSensitive(row,"id"),0,TROPHIES-1,&id)&&
                cJSON_IsNumber(stamp)&&isfinite(stamp->valuedouble)&&
                stamp->valuedouble>0&&stamp->valuedouble<=253402300799.0&&
                floor(stamp->valuedouble)==stamp->valuedouble;
            if(!ok||next.rows[id].unlocked){ok=0;break;}
            next.rows[id].unlocked=1;next.rows[id].timestamp=(uint64_t)stamp->valuedouble;
            next.unlocked++;
        }
    }
    cJSON_Delete(save);cJSON_Delete(doc);
    if(ok)*model=next;
    return ok;
}
/* Missing unlock state means a new profile. Any existing invalid file errors. */
static char *read_file(const wchar_t *path,int *missing) {
    *missing=0;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_WRITE,NULL,OPEN_EXISTING,0,NULL);
    if(file==INVALID_HANDLE_VALUE) {
        DWORD err=GetLastError();*missing=err==ERROR_FILE_NOT_FOUND||err==ERROR_PATH_NOT_FOUND;return NULL;
    }
    LARGE_INTEGER size;char *data=NULL;
    if(GetFileSizeEx(file,&size)&&size.QuadPart>0&&size.QuadPart<2*1024*1024) {
        DWORD length=(DWORD)size.QuadPart,read=0;
        data=(char*)malloc((size_t)length+1);
        if(data&&ReadFile(file,data,length,&read,NULL)&&read==length) {
            data[length]=0;
            if(memchr(data,0,length)){free(data);data=NULL;}
        } else {free(data);data=NULL;}
    }
    CloseHandle(file);return data;
}
static void timestamp_text(const Trophy *t,wchar_t *out,size_t cap) {
    if(!t->unlocked){wcscpy_s(out,cap,L"Bloqueado");return;}
    ULARGE_INTEGER ticks;ticks.QuadPart=(t->timestamp+11644473600ULL)*10000000ULL;
    FILETIME utc={ticks.LowPart,ticks.HighPart},local;SYSTEMTIME date;
    if(FileTimeToLocalFileTime(&utc,&local)&&FileTimeToSystemTime(&local,&date))
        swprintf(out,cap,L"%04u-%02u-%02u %02u:%02u",date.wYear,date.wMonth,date.wDay,date.wHour,date.wMinute);
    else wcscpy_s(out,cap,L"Desbloqueado");
}
static LRESULT CALLBACK trophy_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
    TrophyModel *m=(TrophyModel*)GetWindowLongPtrW(hwnd,GWLP_USERDATA);
    if(msg==WM_CREATE) {
        m=(TrophyModel*)((CREATESTRUCTW*)lp)->lpCreateParams;
        SetWindowLongPtrW(hwnd,GWLP_USERDATA,(LONG_PTR)m);
        wchar_t summary[512];swprintf(summary,_countof(summary),L"%ls — %d / %d trofeos desbloqueados",m->title,m->unlocked,m->count);
        HWND label=CreateWindowW(L"STATIC",summary,WS_CHILD|WS_VISIBLE,18,15,746,35,hwnd,NULL,NULL,NULL);
        m->list=CreateWindowExW(WS_EX_CLIENTEDGE,WC_LISTVIEWW,L"",WS_CHILD|WS_VISIBLE|WS_TABSTOP|LVS_REPORT|LVS_SINGLESEL|LVS_SHOWSELALWAYS,
            18,57,746,325,hwnd,(HMENU)1,NULL,NULL);
        ListView_SetExtendedListViewStyle(m->list,LVS_EX_FULLROWSELECT|LVS_EX_DOUBLEBUFFER);
        const wchar_t *names[]={L"ID",L"Grado",L"Trofeo",L"Estado / fecha local"};
        int widths[]={40,75,365,235};
        for(int i=0;i<4;i++){LVCOLUMNW col={0};col.mask=LVCF_TEXT|LVCF_WIDTH;col.pszText=(LPWSTR)names[i];col.cx=widths[i];ListView_InsertColumn(m->list,i,&col);}
        for(int i=0;i<m->count;i++) {
            Trophy *t=&m->rows[i];wchar_t id[16],when[64];swprintf(id,_countof(id),L"%d",t->id);
            LVITEMW item={0};item.mask=LVIF_TEXT;item.iItem=i;item.pszText=id;ListView_InsertItem(m->list,&item);
            const wchar_t *grades[]={L"",L"Platino",L"Oro",L"Plata",L"Bronce"};
            ListView_SetItemText(m->list,i,1,(LPWSTR)grades[t->grade]);
            ListView_SetItemText(m->list,i,2,(LPWSTR)display_name(t));
            timestamp_text(t,when,_countof(when));ListView_SetItemText(m->list,i,3,when);
        }
        m->detail=CreateWindowExW(WS_EX_CLIENTEDGE,L"EDIT",L"Selecciona un trofeo para ver su descripción.",
            WS_CHILD|WS_VISIBLE|WS_TABSTOP|ES_MULTILINE|ES_READONLY|WS_VSCROLL,18,395,746,105,hwnd,(HMENU)2,NULL,NULL);
        HWND close=CreateWindowW(L"BUTTON",L"Cerrar",WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_DEFPUSHBUTTON,644,515,120,30,hwnd,(HMENU)IDCANCEL,NULL,NULL);
        HFONT font=(HFONT)GetStockObject(DEFAULT_GUI_FONT);
        SendMessageW(label,WM_SETFONT,(WPARAM)font,TRUE);SendMessageW(m->list,WM_SETFONT,(WPARAM)font,TRUE);
        SendMessageW(m->detail,WM_SETFONT,(WPARAM)font,TRUE);SendMessageW(close,WM_SETFONT,(WPARAM)font,TRUE);
        return 0;
    }
    if(msg==WM_NOTIFY&&m&&((NMHDR*)lp)->hwndFrom==m->list&&((NMHDR*)lp)->code==LVN_ITEMCHANGED) {
        int selected=ListView_GetNextItem(m->list,-1,LVNI_SELECTED);
        if(selected>=0&&selected<m->count)SetWindowTextW(m->detail,display_description(&m->rows[selected]));
        return 0;
    }
    if((msg==WM_COMMAND&&LOWORD(wp)==IDCANCEL)||msg==WM_CLOSE){DestroyWindow(hwnd);return 0;}
    return DefWindowProcW(hwnd,msg,wp,lp);
}
void lajungla_show_trophies(HWND owner,const wchar_t *catalog,const wchar_t *state) {
    int missing=0;
    char *catalog_json=read_file(catalog,&missing);
    if(!catalog_json) {
        MessageBoxW(owner,missing?L"Instala tu juego para extraer su catálogo de trofeos.":L"No se pudo leer el catálogo local de trofeos.",L"Trofeos · Tokyo Jungle",MB_OK|MB_ICONINFORMATION);return;
    }
    char *state_json=read_file(state,&missing);
    if(!state_json&&!missing) {free(catalog_json);MessageBoxW(owner,L"No se pudo leer el estado de trofeos. No se han modificado tus archivos.",L"Trofeos · Tokyo Jungle",MB_OK|MB_ICONERROR);return;}
    TrophyModel model={0};int valid=parse_model(catalog_json,state_json,&model);
    free(catalog_json);free(state_json);
    if(!valid) {MessageBoxW(owner,L"El catálogo o el estado local de trofeos es inválido. No se muestran desbloqueos ni se modifican archivos.",L"Trofeos · Tokyo Jungle",MB_OK|MB_ICONERROR);return;}
    INITCOMMONCONTROLSEX controls={sizeof controls,ICC_LISTVIEW_CLASSES};InitCommonControlsEx(&controls);
    WNDCLASSW wc={0};wc.lpfnWndProc=trophy_proc;wc.hInstance=GetModuleHandleW(NULL);
    wc.hCursor=LoadCursorW(NULL,IDC_ARROW);wc.hbrBackground=(HBRUSH)(COLOR_BTNFACE+1);wc.lpszClassName=L"TokyoJungleTrophies";
    RegisterClassW(&wc);
    DWORD style=WS_OVERLAPPED|WS_CAPTION|WS_SYSMENU;RECT r={0,0,784,560};AdjustWindowRect(&r,style,FALSE);
    HWND view=CreateWindowW(wc.lpszClassName,L"Trofeos · Tokyo Jungle",style,CW_USEDEFAULT,CW_USEDEFAULT,r.right-r.left,r.bottom-r.top,owner,NULL,wc.hInstance,&model);
    if(!view){MessageBoxW(owner,L"No se pudo abrir la ventana de trofeos.",L"Tokyo Jungle",MB_OK|MB_ICONERROR);return;}
    EnableWindow(owner,FALSE);ShowWindow(view,SW_SHOW);
    MSG msg;while(IsWindow(view)&&GetMessageW(&msg,NULL,0,0)>0) {
        if(!IsDialogMessageW(view,&msg)){TranslateMessage(&msg);DispatchMessageW(&msg);}
    }
    EnableWindow(owner,TRUE);SetForegroundWindow(owner);
}

/* Synthetic fixtures only. No file I/O or GUI in these tests. */
int lajungla_trophy_selftest(void) {
    char fixture[8192]="{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"title\":\"Fixture\",\"trophies\":[";
    for(int i=0;i<TROPHIES;i++) {
        char row[384];
        snprintf(row,sizeof row,"%s{\"id\":%d,\"grade\":4,\"hidden\":true,\"name\":\"Secret fixture\",\"description\":\"Private description\"}",i?",":"",i);
        strcat_s(fixture,sizeof fixture,row);
    }
    strcat_s(fixture,sizeof fixture,"]}");
    const char *valid="{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":[{\"id\":2,\"timestamp\":1700000000}]}";
    const char *bad[]={
        "{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":[{\"id\":2,\"timestamp\":1},{\"id\":2,\"timestamp\":2}]}",
        "{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":[{\"id\":13,\"timestamp\":1}]}",
        "{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":[{\"id\":2,\"timestamp\":-1}]}",
        "{\"format\":1,\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":[]}",
        "{\"format\":1,\"communication_id\":\"WRONG\",\"trophies\":[]}",
        "{broken",
        "{\"format\":1,\"communication_id\":\"NPWR01344_00\",\"trophies\":null}"
    };
    TrophyModel model={0};
    if(!parse_model(fixture,NULL,&model)||model.count!=13||model.unlocked!=0)return 1;
    if(wcscmp(display_name(&model.rows[0]),L"Trofeo oculto")||
       !wcscmp(display_description(&model.rows[0]),L"Private description"))return 2;
    if(!parse_model(fixture,valid,&model)||model.unlocked!=1||
       wcscmp(display_name(&model.rows[2]),L"Secret fixture"))return 3;
    TrophyModel before=model;
    for(size_t i=0;i<_countof(bad);i++) {
        if(parse_model(fixture,bad[i],&model)||memcmp(&model,&before,sizeof model))return 4;
    }
    char *duplicate=strstr(fixture,"\"id\":12");if(!duplicate)return 5;
    duplicate[5]='1';duplicate[6]='1';
    if(parse_model(fixture,NULL,&model))return 6;
    return 0;
}
