/* TokyoJungle.exe -- launcher with a settings screen (Windows, and SteamOS via Proton).
 *
 * Shows a small window to pick the resolution (1280x720 or 2560x1440) and
 * window/fullscreen, remembers the choice in launcher.ini, then does what
 * `scripts\launch_tokyojungle.ps1 -Run -Recommended` does without PowerShell:
 * sets the same environment, starts the recompiled game and waits for it (so
 * Steam sees the game as running until it closes).
 *
 * Folder layout, relative to this launcher:
 *   NPUA80523\                  extracted game (USRDIR, PARAM.SFO)
 *   engine\  or build\tokyojungle\
 *       tokyojungle.exe  or build-clang\tokyojungle.exe (+ ffmpeg.exe for movies)
 *       input\EBOOT.ELF, input\PARAM.SFO, controls.ini
 *   logs\                        created; stdout.log / stderr.log
 *   launcher.ini                 created; the saved choice
 *
 * Command line: -play starts with the saved choice without the window,
 * -2k forces 2560x1440, -fullscreen forces full screen. Holding Shift while
 * starting shows the window even when "don't ask again" was ticked.
 *
 * For RecompLauncher (recomplauncher.json), only used when passed:
 *   --game <folder>   the extracted game folder, anywhere (instead of [paths] game=)
 *   --prepare         runs BUILD.bat on that folder with no window and passes its
 *                     "progress 0.4 Text" lines through on stdout
 */
#define WIN32_LEAN_AND_MEAN
#define UNICODE
#define _UNICODE
#define COBJMACROS
#include <windows.h>
#include <commdlg.h>
#include <shlobj.h>
#include <shellapi.h>
#include <shobjidl.h>
#include <knownfolders.h>
#include <stdio.h>
#include "trophy_view.h"
#pragma comment(lib, "uuid.lib")
#include <stdlib.h>
#include <wchar.h>

#define MAXP 1024

enum { ID_RES_720 = 101, ID_RES_2K, ID_WINDOWED, ID_FULLSCREEN, ID_SKIP, ID_PLAY, ID_QUIT, ID_PROMPTS, ID_INSTALL, ID_INSTALL_STATUS, ID_LANGUAGE, ID_DESKTOP, ID_STEAM, ID_TROPHIES };

typedef struct {
    int two_k;       /* 0: 1280x720, 1: 2560x1440 */
    int fullscreen;  /* 0: window, 1: borderless full screen */
    int prompts;    /* 0 PlayStation (default), 1 Xbox, 2 Nintendo, 3 keyboard, 4 auto */
    int language;   /* 0 Spanish, 1 English, 2 French, 3 Brazilian Portuguese */
    int skip;        /* 1: start directly next time */
} Settings;

static wchar_t g_base[MAXP];
static wchar_t g_ini[MAXP];
static wchar_t g_launcher[MAXP];
static Settings g_settings;
static int g_play;
static HFONT g_font;
static HANDLE g_install_process;
static wchar_t g_install_log[MAXP];

static int exists(const wchar_t* p) {
    return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES;
}

static void join(wchar_t* out, const wchar_t* a, const wchar_t* b) {
    swprintf(out, MAXP, L"%ls\\%ls", a, b);
}

static int is_absolute(const wchar_t* p) {
    return (p[0] && p[1] == L':') || (p[0] == L'\\' && p[1] == L'\\');
}

static void strip_trailing_slashes(wchar_t* p) {
    size_t n = wcslen(p);
    while (n > 3 && (p[n - 1] == L'\\' || p[n - 1] == L'/')) p[--n] = 0;
}

static int fail(const wchar_t* msg, const wchar_t* path) {
    wchar_t text[2 * MAXP];
    swprintf(text, 2 * MAXP, L"%ls\n\n%ls", msg, path ? path : L"");
    MessageBoxW(NULL, text, L"Tokyo Jungle", MB_OK | MB_ICONERROR);
    return 1;
}

static const wchar_t* prompt_values[] = { L"playstation", L"xbox", L"nintendo", L"keyboard", L"auto" };
static const wchar_t* prompt_labels[] = { L"PlayStation (original)", L"Xbox", L"Nintendo / Switch", L"Teclado", L"Automático (último dispositivo)" };
static const wchar_t* language_values[] = { L"es", L"en", L"fr", L"pt" };
static const wchar_t* language_labels[] = { L"Español", L"English", L"Français", L"Português" };
static int language_setting_index(const wchar_t* value) {
    for (int i = 0; i < 4; ++i) if (_wcsicmp(value, language_values[i]) == 0) return i;
    return 0;
}

static int prompt_setting_index(const wchar_t* value) {
    for (int i = 0; i < 5; ++i) if (_wcsicmp(value, prompt_values[i]) == 0) return i;
    return 0;
}

static void configure_prompt_environment(void) {
    SetEnvironmentVariableW(L"LAJUNGLA_PROMPTS", prompt_values[g_settings.prompts]);
    SetEnvironmentVariableW(L"TJ_PROMPTS", g_settings.prompts == 0 ? L"0" : L"1");
    SetEnvironmentVariableW(L"LAJUNGLA_LANGUAGE", language_values[g_settings.language]);
}

static void load_settings(void) {
    wchar_t prompts[32];
    GetPrivateProfileStringW(L"controls", L"prompt_family", L"playstation", prompts, 32, g_ini);
    g_settings.prompts = prompt_setting_index(prompts);
    wchar_t language[32];
    GetPrivateProfileStringW(L"language", L"locale", L"es", language, 32, g_ini);
    g_settings.language = language_setting_index(language);
    g_settings.two_k = GetPrivateProfileIntW(L"video", L"resolution_2k", 0, g_ini) != 0;
    g_settings.fullscreen = GetPrivateProfileIntW(L"video", L"fullscreen", 0, g_ini) != 0;
    g_settings.skip = GetPrivateProfileIntW(L"launcher", L"dont_ask", 0, g_ini) != 0;
}

static void save_settings(void) {
    WritePrivateProfileStringW(L"controls", L"prompt_family", prompt_values[g_settings.prompts], g_ini);
    WritePrivateProfileStringW(L"language", L"locale", language_values[g_settings.language], g_ini);
    WritePrivateProfileStringW(L"video", L"resolution_2k", g_settings.two_k ? L"1" : L"0", g_ini);
    WritePrivateProfileStringW(L"video", L"fullscreen", g_settings.fullscreen ? L"1" : L"0", g_ini);
    WritePrivateProfileStringW(L"launcher", L"dont_ask", g_settings.skip ? L"1" : L"0", g_ini);
}


/* Append a PowerShell literal without allowing package paths to become code.
 * Windows paths cannot contain double quotes; apostrophes are doubled here. */
static int command_append(wchar_t* out, size_t cap, const wchar_t* text) {
    size_t have = wcslen(out), extra = wcslen(text);
    if (extra >= cap || have >= cap - extra) return 0;
    memcpy(out + have, text, (extra + 1) * sizeof(wchar_t));
    return 1;
}

static int command_ps_literal(wchar_t* out, size_t cap, const wchar_t* text) {
    if (!command_append(out, cap, L"'")) return 0;
    for (; *text; ++text) {
        wchar_t one[2] = { *text, 0 };
        if (*text == L'"' || *text == L'\r' || *text == L'\n') return 0;
        if (!command_append(out, cap, *text == L'\'' ? L"''" : one)) return 0;
    }
    return command_append(out, cap, L"'");
}

static int content_install_command(wchar_t* out, size_t cap, const wchar_t* wrapper,
                                   const wchar_t* root, const wchar_t* packages,
                                   const wchar_t* licenses) {
    out[0] = 0;
    if (!command_append(out, cap, L"powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command \"& ") ||
        !command_ps_literal(out, cap, wrapper) || !command_append(out, cap, L" -Root ") ||
        !command_ps_literal(out, cap, root) || !command_append(out, cap, L" -Packages @(")) return 0;
    const wchar_t* item = packages + wcslen(packages) + 1;
    if (!*item) {
        if (!command_ps_literal(out, cap, packages)) return 0;
    } else {
        int first = 1;
        for (; *item; item += wcslen(item) + 1) {
            wchar_t path[MAXP];
            if (wcslen(packages) + wcslen(item) + 2 >= MAXP) return 0;
            join(path, packages, item);
            if ((!first && !command_append(out, cap, L",")) || !command_ps_literal(out, cap, path)) return 0;
            first = 0;
        }
    }
    return command_append(out, cap, L") -Licenses ") && command_ps_literal(out, cap, licenses) &&
           command_append(out, cap, L"; if (-not $?) { exit 1 }\"");
}

static void start_content_install(HWND hwnd) {
    if (g_install_process) return;
    wchar_t wrapper[MAXP];
    const wchar_t* wrapper_paths[] = { L"tools\\content\\tj_prepare_content.ps1",
        L".build\\tokyojungle\\scripts\\tj_prepare_content.ps1", L"scripts\\tj_prepare_content.ps1" };
    for (int i = 0; i < 3; ++i) {
        join(wrapper, g_base, wrapper_paths[i]);
        if (exists(wrapper)) break;
    }
    if (!exists(wrapper)) { fail(L"O instalador de conteúdo não foi encontrado.", wrapper); return; }
    wchar_t packages[8192] = {0};
    OPENFILENAMEW open = {0}; open.lStructSize = sizeof open;
    open.hwndOwner = hwnd;
    open.lpstrTitle = L"Instalar jogo / DLC: selecione seus arquivos PKG";
    open.lpstrFilter = L"Pacotes PlayStation 3 (*.pkg)\0*.pkg\0Todos os arquivos\0*.*\0\0";
    open.lpstrFile = packages;
    open.nMaxFile = sizeof packages / sizeof packages[0];
    open.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_ALLOWMULTISELECT | OFN_NOCHANGEDIR;
    if (!GetOpenFileNameW(&open)) return;
    HRESULT co = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    BROWSEINFOW browse = {0};
    browse.hwndOwner = hwnd;
    browse.lpszTitle = L"Selecione a pasta com as licenças RAP da sua cópia";
    browse.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE;
    PIDLIST_ABSOLUTE selected = SHBrowseForFolderW(&browse);
    wchar_t licenses[MAXP] = {0};
    int valid = selected && SHGetPathFromIDListW(selected, licenses);
    if (selected) CoTaskMemFree((void*)selected);
    if (SUCCEEDED(co)) CoUninitialize();
    if (!valid) return;
    wchar_t command[32768];
    if (!content_install_command(command, sizeof command / sizeof command[0], wrapper, g_base, packages, licenses)) {
        fail(L"Os caminhos selecionados são longos demais para iniciar a instalação.", NULL); return;
    }
    join(g_install_log, g_base, L"content-setup.log");
    SECURITY_ATTRIBUTES sa = { sizeof sa, NULL, TRUE };
    HANDLE log = CreateFileW(g_install_log, GENERIC_WRITE, FILE_SHARE_READ, &sa, CREATE_ALWAYS, 0, NULL);
    HANDLE input = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
    if (log == INVALID_HANDLE_VALUE || input == INVALID_HANDLE_VALUE) {
        if (log != INVALID_HANDLE_VALUE) CloseHandle(log);
        if (input != INVALID_HANDLE_VALUE) CloseHandle(input);
        fail(L"Não foi possível abrir o log da instalação.", g_install_log); return;
    }
    STARTUPINFOW si = {0}; si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = si.hStdError = log; si.hStdInput = input;
    PROCESS_INFORMATION process = {0};
    BOOL started = CreateProcessW(NULL, command, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, g_base, &si, &process);
    CloseHandle(log); CloseHandle(input);
    if (!started) { fail(L"Não foi possível iniciar a instalação.", g_install_log); return; }
    CloseHandle(process.hThread);
    g_install_process = process.hProcess;
    EnableWindow(GetDlgItem(hwnd, ID_PLAY), FALSE);
    EnableWindow(GetDlgItem(hwnd, ID_INSTALL), FALSE);
    SetDlgItemTextW(hwnd, ID_INSTALL_STATUS, L"Instalando... veja content-setup.log");
    SetTimer(hwnd, 1, 250, NULL);
}

/* Configure in memory first; desktop writes happen only on the explicit button. */
static HRESULT configure_shortcut(IShellLinkW *link) {
    HRESULT hr=IShellLinkW_SetPath(link,g_launcher);
    if(SUCCEEDED(hr))hr=IShellLinkW_SetArguments(link,L"-play");
    if(SUCCEEDED(hr))hr=IShellLinkW_SetWorkingDirectory(link,g_base);
    if(SUCCEEDED(hr))hr=IShellLinkW_SetDescription(link,L"Tokyo Jungle · matymeatboy");
    if(SUCCEEDED(hr))hr=IShellLinkW_SetIconLocation(link,g_launcher,0);
    return hr;
}
static int shortcut_selftest(void) {
    HRESULT hr=CoInitializeEx(NULL,COINIT_APARTMENTTHREADED);
    if(FAILED(hr))return 1;
    IShellLinkW *link=NULL;
    hr=CoCreateInstance(&CLSID_ShellLink,NULL,CLSCTX_INPROC_SERVER,&IID_IShellLinkW,(void**)&link);
    if(SUCCEEDED(hr))hr=configure_shortcut(link);
    wchar_t path[MAXP]=L"",args[64]=L"",directory[MAXP]=L"",icon[MAXP]=L"";
    int index=-1;
    if(SUCCEEDED(hr))hr=IShellLinkW_GetPath(link,path,MAXP,NULL,SLGP_RAWPATH);
    if(SUCCEEDED(hr))hr=IShellLinkW_GetArguments(link,args,_countof(args));
    if(SUCCEEDED(hr))hr=IShellLinkW_GetWorkingDirectory(link,directory,MAXP);
    if(SUCCEEDED(hr))hr=IShellLinkW_GetIconLocation(link,icon,MAXP,&index);
    int ok=SUCCEEDED(hr)&&!_wcsicmp(path,g_launcher)&&!wcscmp(args,L"-play")&&
        !_wcsicmp(directory,g_base)&&!_wcsicmp(icon,g_launcher)&&index==0;
    if(link)IShellLinkW_Release(link);
    CoUninitialize();return ok?0:2;
}
static void create_desktop_shortcut(HWND hwnd) {
    HRESULT initialized=CoInitializeEx(NULL,COINIT_APARTMENTTHREADED);
    if(FAILED(initialized)){fail(L"No se pudo inicializar el acceso directo.",NULL);return;}
    PWSTR desktop=NULL;IShellLinkW *link=NULL;IPersistFile *file=NULL;
    wchar_t target[MAXP],temporary[MAXP];
    HRESULT hr=SHGetKnownFolderPath(&FOLDERID_Desktop,KF_FLAG_DEFAULT,NULL,&desktop);
    if(FAILED(hr)||!desktop) {fail(L"No se pudo localizar el escritorio.",NULL);CoUninitialize();return;}
    join(target,desktop,L"Tokyo Jungle.lnk");
    if(exists(target)) {
        CoTaskMemFree(desktop);
        MessageBoxW(hwnd,L"Ya existe Tokyo Jungle.lnk en el escritorio. Se ha conservado.",L"Tokyo Jungle",MB_OK|MB_ICONINFORMATION);CoUninitialize();return;
    }
    if(!GetTempFileNameW(desktop,L"LJG",0,temporary)) {
        CoTaskMemFree(desktop);fail(L"No se puede escribir en el escritorio.",NULL);CoUninitialize();return;
    }
    CoTaskMemFree(desktop);
    hr=CoCreateInstance(&CLSID_ShellLink,NULL,CLSCTX_INPROC_SERVER,&IID_IShellLinkW,(void**)&link);
    if(SUCCEEDED(hr))hr=configure_shortcut(link);
    if(SUCCEEDED(hr))hr=IShellLinkW_QueryInterface(link,&IID_IPersistFile,(void**)&file);
    if(SUCCEEDED(hr))hr=IPersistFile_Save(file,temporary,TRUE);
    if(file)IPersistFile_Release(file);
    if(link)IShellLinkW_Release(link);
    /* No replace flag: preserve a shortcut another process created meanwhile. */
    if(SUCCEEDED(hr)&&!MoveFileExW(temporary,target,MOVEFILE_WRITE_THROUGH))hr=HRESULT_FROM_WIN32(GetLastError());
    DeleteFileW(temporary);
    if(FAILED(hr))fail(L"No se pudo crear el acceso directo.",target);
    else MessageBoxW(hwnd,L"Acceso directo creado en el escritorio.",L"Tokyo Jungle",MB_OK|MB_ICONINFORMATION);
    CoUninitialize();
}
static void add_to_steam(HWND hwnd) {
    INT_PTR result=(INT_PTR)ShellExecuteW(hwnd,L"open",L"steam://AddNonSteamGame",NULL,NULL,SW_SHOWNORMAL);
    if(result<=32) {
        fail(L"No se pudo abrir Steam. Instálalo o ábrelo y usa Juegos > Añadir un producto que no es de Steam.",g_launcher);return;
    }
    wchar_t text[MAXP+900];
    _snwprintf_s(text,_countof(text),_TRUNCATE,
        L"En Steam, pulsa Buscar y selecciona:\n%ls\n\n"
        L"Después, Añadir seleccionados. En Propiedades, usa -play como opción de lanzamiento.\n\n"
        L"Si no aparece el diálogo: Juegos > Añadir un producto que no es de Steam.\n"
        L"Steam confirma la incorporación; Tokyo Jungle no modifica tu biblioteca directamente.",g_launcher);
    MessageBoxW(hwnd,text,L"Añadir Tokyo Jungle a Steam",MB_OK|MB_ICONINFORMATION);
}
static void show_local_trophies(HWND hwnd) {
    wchar_t configured[MAXP],game[MAXP],catalog[2*MAXP],state[2*MAXP],engine[MAXP],exe[MAXP];
    GetPrivateProfileStringW(L"paths",L"game",L"NPUA80523",configured,MAXP,g_ini);
    if(is_absolute(configured))wcscpy(game,configured);else join(game,g_base,configured);
    join(engine,g_base,L"engine");join(exe,engine,L"tokyojungle.exe");
    if(!exists(exe))join(engine,g_base,L"build\\tokyojungle");
    swprintf(catalog,_countof(catalog),L"%ls\\.lajungla\\trophies\\%ls\\catalog.json",game,language_values[g_settings.language]);
    swprintf(state,_countof(state),L"%ls\\savedata\\trophies\\NPWR01344_00.json",engine);
    lajungla_show_trophies(hwnd,catalog,state);
}

/* ---- settings window ---------------------------------------------------- */

static HWND add(HWND parent, const wchar_t* cls, const wchar_t* text, DWORD style,
                int x, int y, int w, int h, int id) {
    HWND c = CreateWindowExW(0, cls, text, WS_CHILD | WS_VISIBLE | style, x, y, w, h,
                             parent, (HMENU)(INT_PTR)id, GetModuleHandleW(NULL), NULL);
    SendMessageW(c, WM_SETFONT, (WPARAM)g_font, TRUE);
    return c;
}

static LRESULT CALLBACK settings_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        add(hwnd, L"BUTTON", L"Resolução", BS_GROUPBOX, 12, 8, 316, 78, 0);
        add(hwnd, L"BUTTON", L"1280 x 720  (original do PS3, mais leve)",
            BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 24, 30, 296, 22, ID_RES_720);
        add(hwnd, L"BUTTON", L"2560 x 1440  (2K, mais nítido)",
            BS_AUTORADIOBUTTON, 24, 56, 296, 22, ID_RES_2K);
        add(hwnd, L"BUTTON", L"Tela", BS_GROUPBOX, 12, 94, 316, 78, 0);
        add(hwnd, L"BUTTON", L"Janela",
            BS_AUTORADIOBUTTON | WS_GROUP | WS_TABSTOP, 24, 116, 296, 22, ID_WINDOWED);
        add(hwnd, L"BUTTON", L"Tela cheia",
            BS_AUTORADIOBUTTON, 24, 142, 296, 22, ID_FULLSCREEN);
        add(hwnd, L"STATIC", L"Símbolos de controles", 0, 14, 180, 312, 20, 0);
        HWND prompts = add(hwnd, L"COMBOBOX", L"", CBS_DROPDOWNLIST | WS_TABSTOP,
                           14, 202, 312, 160, ID_PROMPTS);
        for (int i = 0; i < 5; ++i) SendMessageW(prompts, CB_ADDSTRING, 0, (LPARAM)prompt_labels[i]);
        SendMessageW(prompts, CB_SETCURSEL, g_settings.prompts, 0);
        add(hwnd, L"STATIC", L"Idioma del juego", 0, 14, 235, 312, 20, 0);
        HWND language = add(hwnd, L"COMBOBOX", L"", CBS_DROPDOWNLIST | WS_TABSTOP,
                            14, 257, 312, 140, ID_LANGUAGE);
        for (int i = 0; i < 4; ++i) SendMessageW(language, CB_ADDSTRING, 0, (LPARAM)language_labels[i]);
        SendMessageW(language, CB_SETCURSEL, g_settings.language, 0);
        add(hwnd, L"BUTTON", L"Añadir juego o DLC (.pkg)…", BS_PUSHBUTTON | WS_TABSTOP,
            14, 294, 312, 30, ID_INSTALL);
        add(hwnd, L"STATIC", L"", 0, 14, 327, 312, 20, ID_INSTALL_STATUS);
        add(hwnd, L"BUTTON", L"Crear acceso directo", BS_PUSHBUTTON | WS_TABSTOP,
            14, 351, 312, 30, ID_DESKTOP);
        add(hwnd, L"BUTTON", L"Añadir a Steam…", BS_PUSHBUTTON | WS_TABSTOP,
            14, 387, 312, 30, ID_STEAM);
        add(hwnd, L"BUTTON", L"Trofeos", BS_PUSHBUTTON | WS_TABSTOP,
            14, 424, 312, 30, ID_TROPHIES);
        add(hwnd, L"BUTTON", L"Não perguntar de novo (segure Shift ao abrir para mudar)",
            BS_AUTOCHECKBOX | WS_GROUP | WS_TABSTOP, 14, 463, 316, 22, ID_SKIP);
        add(hwnd, L"BUTTON", L"Jogar", BS_DEFPUSHBUTTON | WS_GROUP | WS_TABSTOP,
            146, 497, 88, 30, ID_PLAY);
        add(hwnd, L"BUTTON", L"Sair", BS_PUSHBUTTON | WS_TABSTOP, 240, 497, 88, 30, ID_QUIT);
        CheckRadioButton(hwnd, ID_RES_720, ID_RES_2K, g_settings.two_k ? ID_RES_2K : ID_RES_720);
        CheckRadioButton(hwnd, ID_WINDOWED, ID_FULLSCREEN,
                         g_settings.fullscreen ? ID_FULLSCREEN : ID_WINDOWED);
        CheckDlgButton(hwnd, ID_SKIP, g_settings.skip ? BST_CHECKED : BST_UNCHECKED);
        SetFocus(GetDlgItem(hwnd, ID_PLAY));
        return 0;
    }
    case WM_TIMER:
        if (wp == 1 && g_install_process && WaitForSingleObject(g_install_process, 0) == WAIT_OBJECT_0) {
            DWORD code = 1;
            GetExitCodeProcess(g_install_process, &code);
            CloseHandle(g_install_process); g_install_process = NULL;
            KillTimer(hwnd, 1);
            EnableWindow(GetDlgItem(hwnd, ID_PLAY), TRUE);
            EnableWindow(GetDlgItem(hwnd, ID_INSTALL), TRUE);
            SetDlgItemTextW(hwnd, ID_INSTALL_STATUS, code ? L"Falhou: veja content-setup.log" : L"Conteúdo instalado com sucesso.");
            if (code) fail(L"A instalação falhou. Consulte o log para os detalhes.", g_install_log);
        }
        return 0;
    case WM_COMMAND:
        if (LOWORD(wp) == ID_DESKTOP) { create_desktop_shortcut(hwnd); return 0; }
        if (LOWORD(wp) == ID_STEAM) { add_to_steam(hwnd); return 0; }
        if (LOWORD(wp) == ID_TROPHIES) { show_local_trophies(hwnd); return 0; }
        if (LOWORD(wp) == ID_LANGUAGE && HIWORD(wp) == CBN_SELCHANGE) {
            LRESULT selected=SendDlgItemMessageW(hwnd,ID_LANGUAGE,CB_GETCURSEL,0,0);
            g_settings.language=selected>=0&&selected<4?(int)selected:0;
            save_settings();return 0;
        }
        if (LOWORD(wp) == ID_INSTALL) { start_content_install(hwnd); return 0; }
        if (LOWORD(wp) == ID_PLAY || LOWORD(wp) == IDOK) {
            if (g_install_process) return 0;
            g_settings.two_k = IsDlgButtonChecked(hwnd, ID_RES_2K) == BST_CHECKED;
            g_settings.fullscreen = IsDlgButtonChecked(hwnd, ID_FULLSCREEN) == BST_CHECKED;
            const LRESULT selected = SendDlgItemMessageW(hwnd, ID_PROMPTS, CB_GETCURSEL, 0, 0);
            g_settings.prompts = (selected >= 0 && selected < 5) ? (int)selected : 0;
            const LRESULT language = SendDlgItemMessageW(hwnd, ID_LANGUAGE, CB_GETCURSEL, 0, 0);
            g_settings.language = (language >= 0 && language < 4) ? (int)language : 0;
            g_settings.skip = IsDlgButtonChecked(hwnd, ID_SKIP) == BST_CHECKED;
            g_play = 1;
            DestroyWindow(hwnd);
        } else if (LOWORD(wp) == ID_QUIT || LOWORD(wp) == IDCANCEL) {
            if (g_install_process) return 0;
            DestroyWindow(hwnd);
        }
        return 0;
    case WM_CLOSE:
        if (g_install_process) {
            MessageBoxW(hwnd,L"Espera a que termine la instalación antes de cerrar.",L"Tokyo Jungle",MB_OK|MB_ICONINFORMATION);
            return 0;
        }
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        if (g_install_process) { CloseHandle(g_install_process); g_install_process = NULL; }
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

/* Returns 1 to start the game, 0 if the player chose Sair. */
static int show_settings(HINSTANCE inst) {
    NONCLIENTMETRICSW ncm = {0}; ncm.cbSize = sizeof ncm;
    SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof ncm, &ncm, 0);
    g_font = CreateFontIndirectW(&ncm.lfMessageFont);

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = settings_proc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.hIcon = LoadIconW(NULL, IDI_APPLICATION);
    wc.lpszClassName = L"TokyoJungleLauncher";
    RegisterClassW(&wc);

    const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    RECT r = {0, 0, 340, 541};
    AdjustWindowRect(&r, style, FALSE);
    const int w = r.right - r.left, h = r.bottom - r.top;
    HWND hwnd = CreateWindowW(wc.lpszClassName, L"Tokyo Jungle", style,
                              (GetSystemMetrics(SM_CXSCREEN) - w) / 2,
                              (GetSystemMetrics(SM_CYSCREEN) - h) / 2,
                              w, h, NULL, NULL, inst, NULL);
    ShowWindow(hwnd, SW_SHOW);
    SetForegroundWindow(hwnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (!IsDialogMessageW(hwnd, &msg)) {  /* Tab, Enter = Jogar, Esc = Sair */
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    DeleteObject(g_font);
    return g_play;
}

/* ---- RecompLauncher setup step (--prepare) --------------------------------- */

/* Runs BUILD.bat next to this launcher on the game folder, without a window.
 * Its output (with tj_build_all.ps1's "progress" lines) goes to our stdout,
 * which RecompLauncher reads. Returns BUILD.bat's exit code. */
static int prepare(const wchar_t* game) {
    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    wchar_t bat[MAXP];
    join(bat, g_base, L"BUILD.bat");
    if (!exists(bat)) {
        static const char msg[] = "progress 0 BUILD.bat is missing next to TokyoJungle.exe\n";
        DWORD n;
        if (out && out != INVALID_HANDLE_VALUE) WriteFile(out, msg, sizeof msg - 1, &n, NULL);
        return 2;
    }

    wchar_t g[MAXP] = L"";
    if (game) {
        wcsncpy(g, game, MAXP - 1);
        g[MAXP - 1] = 0;
        strip_trailing_slashes(g);  /* "C:\x\" would end the quoted argument early */
    }
    wchar_t cmd[3 * MAXP];
    swprintf(cmd, 3 * MAXP, L"cmd.exe /d /s /c \"\"%ls\" -Progress%ls%ls%ls\"", bat,
             g[0] ? L" -Game \"" : L"", g, g[0] ? L"\"" : L"");

    SECURITY_ATTRIBUTES sa = { sizeof sa, NULL, TRUE };
    HANDLE in = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa,
                            OPEN_EXISTING, 0, NULL);
    if (out && out != INVALID_HANDLE_VALUE) SetHandleInformation(out, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    if (err && err != INVALID_HANDLE_VALUE) SetHandleInformation(err, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    STARTUPINFOW si = {0}; si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = in;
    si.hStdOutput = out;
    si.hStdError = (err && err != INVALID_HANDLE_VALUE) ? err : out;

    SetEnvironmentVariableW(L"TJ_NO_PAUSE", L"1");  /* BUILD.bat ends without "pause" */
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, g_base, &si, &pi))
        return 3;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (in != INVALID_HANDLE_VALUE) CloseHandle(in);
    return (int)code;
}

/* ---- game start ------------------------------------------------------------ */

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show) {
    (void)prev; (void)show; (void)cmdline;

    wchar_t self[MAXP];
    GetModuleFileNameW(NULL, self, MAXP);
    wcscpy(g_launcher, self);
    wcscpy(g_base, self);
    wchar_t* slash = wcsrchr(g_base, L'\\');
    if (slash) *slash = 0;
    const wchar_t* selfname = slash ? slash + 1 : self;
    join(g_ini, g_base, L"launcher.ini");
    load_settings();
    for (int i = 1; i < __argc; ++i) {
        if (!_wcsicmp(__wargv[i], L"--check-settings")) {
            if (i+1<__argc && is_absolute(__wargv[i+1])) {wcsncpy(g_ini,__wargv[i+1],MAXP-1);g_ini[MAXP-1]=0;load_settings();}
            wprintf(L"language=%ls\nprompt_family=%ls\nresolution_2k=%d\nfullscreen=%d\n",
                    language_values[g_settings.language], prompt_values[g_settings.prompts],
                    g_settings.two_k, g_settings.fullscreen);
            return 0;
        }
        if (!_wcsicmp(__wargv[i], L"--self-test")) {
            if (lajungla_trophy_selftest()) return 13;
            if (shortcut_selftest()) return 14;
            for (int j = 0; j < 4; ++j) if (language_setting_index(language_values[j]) != j) return 11;
            if (language_setting_index(L"invalid") != 0 || language_setting_index(L"FR") != 2) return 12;
            return 0;
        }
    }

    /* Arguments one by one, so a --game path can't be read as an option. */
    int arg_play = 0, arg_2k = 0, arg_full = 0, arg_prepare = 0;
    const wchar_t* arg_game = NULL;
    for (int i = 1; i < __argc; i++) {
        const wchar_t* a = __wargv[i];
        if (!_wcsicmp(a, L"--game") && i + 1 < __argc) arg_game = __wargv[++i];
        else if (!_wcsicmp(a, L"--prepare")) arg_prepare = 1;
        else if (wcsstr(a, L"-play")) arg_play = 1;
        else if (wcsstr(a, L"-2k") || wcsstr(a, L"-2K")) arg_2k = 1;
        else if (wcsstr(a, L"-fullscreen")) arg_full = 1;
    }
    if (wcsstr(selfname, L"2K") || wcsstr(selfname, L"2k")) arg_2k = 1;
    if (arg_prepare) return prepare(arg_game);
    const int shift = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;

    if (!arg_play && !arg_2k && !arg_full && (!g_settings.skip || shift)) {
        if (!show_settings(inst)) return 0;
        save_settings();
    }
    if (arg_2k) g_settings.two_k = 1;
    if (arg_full) g_settings.fullscreen = 1;

    /* Locate the engine folder and the recompiled executable. */
    wchar_t engine[MAXP], exe[MAXP], tmp[MAXP];
    const wchar_t* engine_dirs[] = { L"engine", L"build\\tokyojungle" };
    const wchar_t* exe_names[]   = { L"tokyojungle.exe", L"build-clang\\tokyojungle.exe" };
    int found = 0;
    for (int i = 0; i < 2 && !found; i++) {
        join(engine, g_base, engine_dirs[i]);
        for (int j = 0; j < 2 && !found; j++) {
            join(exe, engine, exe_names[j]);
            if (exists(exe)) found = 1;
        }
    }
    if (!found)
        return fail(L"Não encontrei o jogo (tokyojungle.exe) em engine\\ ou build\\tokyojungle\\ ao lado deste launcher.", g_base);

    join(tmp, engine, L"input\\EBOOT.ELF");
    if (!exists(tmp)) return fail(L"Falta o EBOOT.ELF descriptografado:", tmp);
    join(tmp, engine, L"input\\PARAM.SFO");
    if (!exists(tmp)) return fail(L"Falta o PARAM.SFO:", tmp);

    /* Game folder: --game, else [paths] game= in launcher.ini (written by
     * BUILD.bat; a name next to this launcher or a full path), NPUA80523 by default. */
    wchar_t game_dir[MAXP], game[MAXP];
    if (arg_game) {
        wcsncpy(game_dir, arg_game, MAXP - 1);
        game_dir[MAXP - 1] = 0;
    } else {
        GetPrivateProfileStringW(L"paths", L"game", L"NPUA80523", game_dir, MAXP, g_ini);
    }
    strip_trailing_slashes(game_dir);
    if (is_absolute(game_dir)) wcscpy(game, game_dir);
    else join(game, g_base, game_dir);
    join(tmp, game, L"USRDIR");
    if (!exists(tmp)) return fail(L"Falta a pasta do jogo extraído (NPUA80523 com USRDIR dentro):", game);

    wchar_t saves[MAXP], cache[MAXP], controls[MAXP], logs[MAXP], out_log[MAXP], err_log[MAXP];
    join(saves, engine, L"savedata");
    join(cache, engine, L"shader-cache");
    join(controls, engine, L"controls.ini");
    join(logs, g_base, L"logs");
    CreateDirectoryW(saves, NULL);
    CreateDirectoryW(cache, NULL);
    CreateDirectoryW(logs, NULL);
    join(out_log, logs, L"stdout.log");
    join(err_log, logs, L"stderr.log");

    configure_prompt_environment();

    /* Same environment as launch_tokyojungle.ps1 -Run -Recommended. */
    SetEnvironmentVariableW(L"PS3_VFS_ROOT", game);
    SetEnvironmentVariableW(L"PS3_HDD_GAME_ROOT", game);
    SetEnvironmentVariableW(L"PS3_VFS_READONLY", L"1");
    SetEnvironmentVariableW(L"PS3_TITLE", L"Tokyo Jungle");
    SetEnvironmentVariableW(L"PS3_SAVEDATA_ROOT", saves);
    SetEnvironmentVariableW(L"TJ_SHADER_CACHE_DIR", cache);
    SetEnvironmentVariableW(L"TJ_CONTROLS_FILE", controls);
    SetEnvironmentVariableW(L"TJ_STDOUT_FILE", out_log);
    SetEnvironmentVariableW(L"TJ_STDERR_FILE", err_log);

    static const wchar_t* recommended[][2] = {
        { L"TJ_AUDIO_BUFFER_MS", L"60" },       { L"TJ_AUDIO_MMCSS", L"1" },
        { L"TJ_BLIT_CLIP_ABSOLUTE", L"1" },     { L"TJ_BLIT_SNAPSHOT_POOL", L"1" },
        { L"TJ_DISABLE_MLAA", L"1" },           { L"TJ_EDGE_NOWAIT", L"1" },
        { L"TJ_FIFO_KICK_WAIT", L"1" },         { L"TJ_FLIP30_LIMIT", L"9" },
        { L"TJ_FLIP_PROMOTE", L"1" },           { L"TJ_FPS_TRACE", L"1" },
        { L"TJ_GCM_INTERRUPT_WORKER", L"1" },   { L"TJ_GPU_COMPLETION_REUSE", L"1" },
        { L"TJ_HIGH_QOS", L"1" },               { L"TJ_LABEL_EARLY_MEMO", L"1" },
        { L"TJ_LOOKUP_FASTPATH", L"1" },        { L"TJ_PREFIX_OVERLAP", L"1" },
        { L"TJ_PREFIX_OWNERSHIP", L"1" },       { L"TJ_PREFIX_QUEUED_PAIR", L"1" },
        { L"TJ_PREFIX_QUEUE_AHEAD", L"1" },     { L"TJ_PREFIX_REPLAY_PREPARE", L"1" },
        { L"TJ_SHADER_PREFETCH", L"1" },        { L"TJ_SNAPSHOT_LATE_PROOF", L"1" },
        { L"TJ_SPU_CTX_REUSE", L"1" },          { L"TJ_TEXTURE_LABEL_BATCH", L"1" },
        { L"TJ_TEXTURE_LABEL_CAP", L"32" },     { L"TJ_TEXTURE_LABEL_EARLY", L"3" },
        { L"TJ_TEXTURE_SNAPSHOT_HINT_RETARGET", L"1" },
        { L"TJ_TEXTURE_SNAPSHOT_RETAIN", L"1" },{ L"TJ_TEXTURE_WRITE_WATCH", L"1" },
        { L"TJ_VERTEX_PARALLEL", L"8" },        { L"TJ_VERTEX_PLAN", L"1" },
        { L"TJ_VP_UCODE_HASH_REUSE", L"1" },
    };
    for (size_t i = 0; i < sizeof recommended / sizeof recommended[0]; i++)
        SetEnvironmentVariableW(recommended[i][0], recommended[i][1]);

    if (g_settings.two_k) {
        SetEnvironmentVariableW(L"TJ_RENDER_SCALE", L"2");
        SetEnvironmentVariableW(L"TJ_VBLANK_SOURCE", L"display");
        SetEnvironmentVariableW(L"TJ_PRESENT_PHASE", L"1");
    }
    if (g_settings.fullscreen)
        SetEnvironmentVariableW(L"TJ_WINDOW_MODE", L"borderless");

    /* Start the game with the engine folder as working directory and wait. */
    wchar_t cmd[MAXP + 4];
    swprintf(cmd, MAXP + 4, L"\"%ls\"", exe);
    STARTUPINFOW si = {0}; si.cb = sizeof si;
    PROCESS_INFORMATION pi;
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, engine, &si, &pi))
        return fail(L"Não consegui iniciar o jogo:", exe);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    /* A crash ends the game with an NTSTATUS error code (0xC0000005 access
     * violation, 0xC0000409 fail-fast, 0xC00000FD stack overflow...). Say so
     * and point at the files a bug report needs. */
    if (code >= 0xC0000000u || code == 0x80000003u) {
        wchar_t text[MAXP + 768];
        swprintf(text, MAXP + 768,
                 L"Tokyo Jungle closed unexpectedly (error 0x%08lX).\n\n"
                 L"To report it, attach stderr.log, stdout.log and any crash-*.dmp from:\n%ls\n\n"
                 L"O jogo fechou inesperadamente. Para reportar, anexe esses arquivos da pasta acima.\n\n"
                 L"Open the logs folder? / Abrir a pasta?",
                 (unsigned long)code, logs);
        if (MessageBoxW(NULL, text, L"Tokyo Jungle", MB_YESNO | MB_ICONERROR) == IDYES) {
            wchar_t open[MAXP + 32];
            swprintf(open, MAXP + 32, L"explorer.exe \"%ls\"", logs);
            STARTUPINFOW esi = {0}; esi.cb = sizeof esi;
            PROCESS_INFORMATION epi;
            if (CreateProcessW(NULL, open, NULL, NULL, FALSE, 0, NULL, NULL, &esi, &epi)) {
                CloseHandle(epi.hThread);
                CloseHandle(epi.hProcess);
            }
        }
    }
    return (int)code;
}
