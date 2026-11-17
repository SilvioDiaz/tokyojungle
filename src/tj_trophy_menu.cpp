// SPDX-License-Identifier: MIT
// Original CPU trophy browser artwork and read-only compositor by matymeatboy.
#include "tj_trophy_menu.h"
#include "lajungla_trophies.h"
#define NOMINMAX
#include <algorithm>
#include <array>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <string>
#include <vector>
#include <wincodec.h>
#include <windows.h>
#include <wrl/client.h>
using Microsoft::WRL::ComPtr;
namespace {
std::array<lajungla_trophy_view, 13> rows{};
int selected = 0, earned = 0, snapshotStatus = 0, top = 0, visible = 13;
bool opened = false, dirty = true;
std::string catalog, language = "es";
unsigned lastW = 0, lastH = 0;
std::vector<unsigned char> badge;
int badgeId = -1;
bool badgeLocked = false;
std::wstring wide(const char *s) {
  int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0);
  if (n < 1)
    return {};
  std::wstring out(n, 0);
  MultiByteToWideChar(CP_UTF8, 0, s, -1, out.data(), n);
  out.pop_back();
  return out;
}
const wchar_t *local(const wchar_t *es, const wchar_t *en, const wchar_t *fr,
                     const wchar_t *pt) {
  return language == "en"   ? en
         : language == "fr" ? fr
         : language == "pt" ? pt
                            : es;
}
std::wstring displayName(const lajungla_trophy_view &r) {
  return r.hidden && !r.unlocked ? local(L"Trofeo secreto", L"Secret trophy",
                                         L"Trophée secret", L"Troféu secreto")
                                 : wide(r.name);
}
COLORREF gradeColor(const lajungla_trophy_view &r) {
  return !r.unlocked    ? RGB(128, 128, 128)
         : r.grade == 2 ? RGB(238, 192, 66)
         : r.grade == 3 ? RGB(211, 222, 235)
                        : RGB(202, 141, 88);
}
void loadBadge(const lajungla_trophy_view &r) {
  badge.clear();
  badgeId = (int)r.id;
  badgeLocked = !r.unlocked;
  if (r.hidden && !r.unlocked)
    return;
  wchar_t filename[32];
  swprintf_s(filename, L"TROP%03u.PNG", r.id);
  auto path = std::filesystem::path(wide(catalog.c_str())).parent_path() /
              L"icons" / filename;
  std::error_code ec;
  auto bytes = std::filesystem::file_size(path, ec);
  if (ec || !bytes || bytes > 1024 * 1024)
    return;
  HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  {
    ComPtr<IWICImagingFactory> f;
    ComPtr<IWICBitmapDecoder> d;
    ComPtr<IWICBitmapFrameDecode> frame;
    ComPtr<IWICBitmapScaler> s;
    ComPtr<IWICFormatConverter> c;
    UINT w = 0, h = 0;
    if (SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr,
                                   CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&f))) &&
        SUCCEEDED(
            f->CreateDecoderFromFilename(path.c_str(), nullptr, GENERIC_READ,
                                         WICDecodeMetadataCacheOnDemand, &d)) &&
        SUCCEEDED(d->GetFrame(0, &frame)) &&
        SUCCEEDED(frame->GetSize(&w, &h)) && w && h && w <= 512 && h <= 512 &&
        SUCCEEDED(f->CreateBitmapScaler(&s)) &&
        SUCCEEDED(s->Initialize(frame.Get(), 96, 96,
                                WICBitmapInterpolationModeFant)) &&
        SUCCEEDED(f->CreateFormatConverter(&c)) &&
        SUCCEEDED(c->Initialize(s.Get(), GUID_WICPixelFormat32bppBGRA,
                                WICBitmapDitherTypeNone, nullptr, 0,
                                WICBitmapPaletteTypeCustom))) {
      badge.resize(96 * 96 * 4);
      if (FAILED(c->CopyPixels(nullptr, 384, (UINT)badge.size(), badge.data())))
        badge.clear();
    }
  }
  if (SUCCEEDED(init))
    CoUninitialize();
}
struct Canvas {
  HDC dc = nullptr;
  HBITMAP bm = nullptr;
  HGDIOBJ old = nullptr;
  unsigned char *bits = nullptr;
  int w, h;
  Canvas(int width, int height) : w(width), h(height) {
    dc = CreateCompatibleDC(nullptr);
    if (!dc)
      return;
    BITMAPINFO info{};
    info.bmiHeader = {sizeof(BITMAPINFOHEADER), w, -h, 1, 32, BI_RGB};
    bm =
        CreateDIBSection(dc, &info, DIB_RGB_COLORS, (void **)&bits, nullptr, 0);
    if (bm)
      old = SelectObject(dc, bm);
  }
  ~Canvas() {
    if (old)
      SelectObject(dc, old);
    if (bm)
      DeleteObject(bm);
    if (dc)
      DeleteDC(dc);
  }
  void rect(int x, int y, int width, int height, COLORREF color) {
    RECT r{x, y, x + width, y + height};
    HBRUSH b = CreateSolidBrush(color);
    FillRect(dc, &r, b);
    DeleteObject(b);
  }
  void text(const std::wstring &s, int x, int y, int width, int height,
            int size, COLORREF color = RGB(232, 237, 242), bool wrap = false) {
    HFONT f = CreateFontW(-size, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                          0, 0, ANTIALIASED_QUALITY, 0, L"Segoe UI");
    auto oldf = SelectObject(dc, f);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, color);
    RECT r{x, y, x + width, y + height};
    DrawTextW(dc, s.c_str(), (int)s.size(), &r,
              DT_NOPREFIX |
                  (wrap ? DT_WORDBREAK
                        : DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS));
    SelectObject(dc, oldf);
    DeleteObject(f);
  }
  void cup(int x, int y, int size, COLORREF color) {
    auto b = CreateSolidBrush(color);
    auto p = CreatePen(PS_SOLID, std::max(2, size / 14), color);
    auto ob = SelectObject(dc, b);
    auto op = SelectObject(dc, p);
    POINT bowl[] = {{x + size * 25 / 100, y + size * 16 / 100},
                    {x + size * 75 / 100, y + size * 16 / 100},
                    {x + size * 65 / 100, y + size * 56 / 100},
                    {x + size * 53 / 100, y + size * 64 / 100},
                    {x + size * 47 / 100, y + size * 64 / 100},
                    {x + size * 35 / 100, y + size * 56 / 100}};
    Polygon(dc, bowl, 6);
    MoveToEx(dc, x + size * 27 / 100, y + size * 24 / 100, nullptr);
    LineTo(dc, x + size * 12 / 100, y + size * 24 / 100);
    LineTo(dc, x + size * 17 / 100, y + size * 43 / 100);
    LineTo(dc, x + size * 36 / 100, y + size * 49 / 100);
    MoveToEx(dc, x + size * 73 / 100, y + size * 24 / 100, nullptr);
    LineTo(dc, x + size * 88 / 100, y + size * 24 / 100);
    LineTo(dc, x + size * 83 / 100, y + size * 43 / 100);
    LineTo(dc, x + size * 64 / 100, y + size * 49 / 100);
    rect(x + size * 46 / 100, y + size * 60 / 100, size * 8 / 100,
         size * 20 / 100, color);
    rect(x + size * 30 / 100, y + size * 81 / 100, size * 40 / 100,
         std::max(2, size * 7 / 100), color);
    SelectObject(dc, op);
    SelectObject(dc, ob);
    DeleteObject(p);
    DeleteObject(b);
  }
};
} // namespace
extern "C" void tj_trophy_menu_configure(const char *p, const char *l) {
  catalog = p ? p : "";
  language = l ? l : "es";
  rows = {};
  badge.clear();
  badgeId = -1;
  selected = top = 0;
  dirty = true;
  opened = false;
}
extern "C" void tj_trophy_menu_open() {
  opened = true;
  dirty = true;
}
extern "C" void tj_trophy_menu_key(int vk, long) {
  int before = selected;
  switch (vk) {
  case VK_UP:
    selected--;
    break;
  case VK_DOWN:
    selected++;
    break;
  case VK_HOME:
    selected = 0;
    break;
  case VK_END:
    selected = 12;
    break;
  case VK_PRIOR:
    selected -= visible;
    break;
  case VK_NEXT:
    selected += visible;
    break;
  }
  selected = std::clamp(selected, 0, 12);
  dirty |= before != selected;
}
extern "C" int tj_trophy_menu_render(void *bgra, unsigned pitch, unsigned width,
                                     unsigned height) {
  if (!opened || !bgra || width < 640 || height < 480 || width > 8192 ||
      height > 8192 || pitch < width * 4ull)
    return 0;
  std::array<lajungla_trophy_view, 13> next{};
  int status = lajungla_trophies_snapshot(next.data(), 13);
  if (status != 13 && status != 0)
    status = -1;
  if (status != snapshotStatus ||
      memcmp(rows.data(), next.data(), sizeof(rows))) {
    rows = next;
    snapshotStatus = status;
    dirty = true;
  }
  if (width != lastW || height != lastH) {
    dirty = true;
    lastW = width;
    lastH = height;
  }
  if (!dirty)
    return 0;
  Canvas c(width, height);
  if (!c.bits)
    return 0;
  dirty = false;
  c.rect(0, 0, width, height, RGB(20, 25, 33));
  c.text(local(L"Trofeos", L"Trophies", L"Trophées", L"Troféus"), 30, 16,
         width - 60, 44, 30);
  if (status != 13) {
    c.text(status < 0
               ? local(L"No se puede leer el progreso de trofeos.",
                       L"Trophy progress could not be read.",
                       L"Impossible de lire la progression des trophées.",
                       L"Não foi possível ler o progresso dos troféus.")
               : local(L"Trofeos no disponibles.", L"Trophies unavailable.",
                       L"Trophées indisponibles.", L"Troféus indisponíveis."),
           30, 100, width - 60, 100, 23, RGB(232, 237, 242), true);
  } else {
    earned = 0;
    for (const auto &r : rows)
      earned += !!r.unlocked;
    c.text(std::to_wstring(earned) + L" / 13", width - 160, 18, 130, 40, 27);
    c.rect(30, 72, width - 60, 5, RGB(62, 70, 82));
    c.rect(30, 72, (width - 60) * earned / 13, 5, RGB(89, 180, 202));
    c.text(local(L"1 oro · 3 plata · 9 bronce   |   Consulta con la partida en pausa",
                 L"1 gold · 3 silver · 9 bronze   |   Pause gameplay before browsing",
                 L"1 or · 3 argent · 9 bronze   |   En partie, utilisez la pause",
                 L"1 ouro · 3 prata · 9 bronze   |   Pausa a partida para consultar"),
           30, 83, width - 60, 26, 16, RGB(165, 176, 190));
    int left = width * 55 / 100, rowH = 34;
    visible = std::min(13, ((int)height - 158) / rowH);
    if (selected < top)
      top = selected;
    if (selected >= top + visible)
      top = selected - visible + 1;
    for (int i = top; i < std::min(13, top + visible); i++) {
      int y = 120 + (i - top) * rowH;
      if (i == selected)
        c.rect(24, y, left - 40, rowH - 2, RGB(47, 72, 91));
      c.cup(34, y + 1, 30, gradeColor(rows[i]));
      c.text(displayName(rows[i]), 77, y, left - 105, rowH, 17,
             rows[i].unlocked ? RGB(240, 242, 245) : RGB(154, 163, 175));
    }
    c.rect(left, 120, 1, height - 170, RGB(66, 75, 89));
    int x = left + 26, dw = width - x - 28;
    auto &r = rows[selected];
    if (badgeId != (int)r.id || badgeLocked != !r.unlocked)
      loadBadge(r);
    c.rect(x, 122, 104, 104, RGB(32, 39, 49));
    if (!badge.empty())
      for (int y = 0; y < 96; y++)
        for (int xx = 0; xx < 96; xx++) {
          auto *s = &badge[(y * 96 + xx) * 4];
          auto *d = c.bits + ((y + 126) * width + x + 4 + xx) * 4;
          unsigned gray = (s[0] * 29 + s[1] * 150 + s[2] * 77) / 256;
          for (int k = 0; k < 3; k++)
            d[k] =
                ((r.unlocked ? s[k] : gray) * s[3] + d[k] * (255 - s[3])) / 255;
        }
    else
      c.text(L"?", x + 31, 143, 60, 55, 42, RGB(132, 144, 158));
    c.cup(x + 120, 143, 65, gradeColor(r));
    c.text(displayName(r), x, 244, dw, 70, 23, RGB(240, 242, 245), true);
    std::wstring description =
        r.hidden && !r.unlocked
            ? local(L"Sigue jugando para descubrir este trofeo.",
                    L"Keep playing to discover this trophy.",
                    L"Continuez à jouer pour découvrir ce trophée.",
                    L"Continue jogando para descobrir este troféu.")
            : wide(r.description);
    c.text(description, x, 321, dw, height - 410, 18, RGB(179, 190, 204), true);
    std::wstring state =
        r.unlocked
            ? local(L"Desbloqueado", L"Unlocked", L"Débloqué", L"Desbloqueado")
            : local(L"Bloqueado", L"Locked", L"Verrouillé", L"Bloqueado");
    if (r.unlocked && r.timestamp) {
      time_t t = (time_t)r.timestamp;
      tm date{};
      if (!localtime_s(&date, &t)) {
        wchar_t b[64];
        wcsftime(b, 64, L" · %Y-%m-%d %H:%M", &date);
        state += b;
      }
    }
    c.text(state, x, height - 78, dw, 28, 17, RGB(162, 180, 193));
  }
  c.text(local(L"↑ ↓ Seleccionar   ·   Inicio / Fin   ·   F3 / Esc Cerrar",
               L"↑ ↓ Select   ·   Home / End   ·   F3 / Esc Close",
               L"↑ ↓ Choisir   ·   Début / Fin   ·   F3 / Échap Fermer",
               L"↑ ↓ Selecionar   ·   Início / Fim   ·   F3 / Esc Fechar"),
         30, height - 36, width - 60, 25, 15, RGB(144, 158, 176));
  GdiFlush();
  for (unsigned y = 0; y < height; y++) {
    auto *d = (unsigned char *)bgra + y * pitch;
    memcpy(d, c.bits + y * width * 4, width * 4);
    for (unsigned x = 0; x < width; x++)
      d[x * 4 + 3] = 255;
  }
  return 1;
}

