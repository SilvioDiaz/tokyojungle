// SPDX-License-Identifier: MIT
// Original CPU trophy notification artwork and compositor by matymeatboy.
#include "tj_trophy_popup.h"
#define NOMINMAX
#include <algorithm>
#include <array>
#include <cmath>
#include <deque>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <string>
#include <vector>
#include <wincodec.h>
#include <windows.h>
#include <wrl/client.h>
using Microsoft::WRL::ComPtr;
namespace {
constexpr unsigned W = 384, H = 96;
struct Event {
  uint32_t id;
  std::string name;
  bool preview = false;
};
std::mutex mutex;
std::deque<Event> queue;
uint32_t seen = 0;
std::string catalog, language = "es";
std::array<std::string, 13> previewNames{};
Event active{};
bool showing = false;
uint64_t started = 0, last = 0;
std::array<unsigned char, W * H * 4> image{};
std::wstring wide(const std::string &s) {
  if (s.empty())
    return {};
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(),
                              (int)s.size(), nullptr, 0);
  if (!n)
    return L"Trofeo";
  std::wstring r(n, 0);
  MultiByteToWideChar(CP_UTF8, 0, s.data(), (int)s.size(), r.data(), n);
  return r;
}
void pixel(int x, int y, unsigned r, unsigned g, unsigned b, unsigned a = 255) {
  if (x < 0 || y < 0 || x >= W || y >= H)
    return;
  auto *p = &image[(y * W + x) * 4];
  unsigned inv = 255 - a;
  p[0] = (b * a + p[0] * inv + 127) / 255;
  p[1] = (g * a + p[1] * inv + 127) / 255;
  p[2] = (r * a + p[2] * inv + 127) / 255;
  p[3] = a + (p[3] * inv + 127) / 255;
}
void cup(int x, int y, int size, unsigned id) {
  unsigned r = id == 0  ? 231
               : id < 4 ? 211
                        : 193,
           g = id == 0  ? 190
               : id < 4 ? 218
                        : 131,
           b = id == 0  ? 65
               : id < 4 ? 226
                        : 80;
  for (int j = 0; j < size; j++)
    for (int i = 0; i < size; i++) {
      float u = float(i) / size, v = float(j) / size;
      bool bowl = v > .15f && v < .57f && u > .25f + (v - .15f) * .25f &&
                  u < .75f - (v - .15f) * .25f;
      bool stem = v >= .56f && v < .8f && u > .46f && u < .55f;
      bool base = v >= .79f && v < .89f && u > .3f && u < .7f;
      bool handles = v > .2f && v < .46f &&
                     ((u > .13f && u < .29f) || (u > .71f && u < .87f));
      if (bowl || stem || base || handles)
        pixel(x + i, y + j, r, g, b);
    }
}
void text(const std::wstring &s, int x, int y, int width, int height,
          int fontSize) {
  HDC dc = CreateCompatibleDC(nullptr);
  if (!dc)
    return;
  BITMAPINFO bi{};
  bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
  bi.bmiHeader.biWidth = W;
  bi.bmiHeader.biHeight = -(int)H;
  bi.bmiHeader.biPlanes = 1;
  bi.bmiHeader.biBitCount = 32;
  bi.bmiHeader.biCompression = BI_RGB;
  void *bits = nullptr;
  HBITMAP bm = CreateDIBSection(dc, &bi, DIB_RGB_COLORS, &bits, nullptr, 0);
  if (!bm) {
    DeleteDC(dc);
    return;
  }
  auto old = SelectObject(dc, bm);
  memset(bits, 0, W * H * 4);
  HFONT font =
      CreateFontW(-fontSize, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                  DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                  ANTIALIASED_QUALITY, DEFAULT_PITCH, L"Segoe UI");
  auto oldfont = SelectObject(dc, font);
  SetBkColor(dc, RGB(0, 0, 0));
  SetTextColor(dc, RGB(255, 255, 255));
  RECT rect{x, y, x + width, y + height};
  DrawTextW(dc, s.c_str(), (int)s.size(), &rect,
            DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS | DT_NOPREFIX);
  // GDI writes RGB coverage but leaves alpha undefined. Rebuild premultiplied
  // alpha.
  auto *mask = (unsigned char *)bits;
  for (unsigned j = 0; j < H; j++)
    for (unsigned i = 0; i < W; i++) {
      unsigned a = std::max({mask[(j * W + i) * 4], mask[(j * W + i) * 4 + 1],
                             mask[(j * W + i) * 4 + 2]});
      if (a)
        pixel(i, j, 248, 248, 248, a);
    }
  SelectObject(dc, oldfont);
  DeleteObject(font);
  SelectObject(dc, old);
  DeleteObject(bm);
  DeleteDC(dc);
}
bool icon(const std::string &path, unsigned id) {
  std::error_code ec;
  auto p = std::filesystem::path(wide(path)).parent_path() / L"icons";
  wchar_t file[32];
  swprintf_s(file, L"TROP%03u.PNG", id);
  p /= file;
  auto bytes = std::filesystem::file_size(p, ec);
  if (ec || !bytes || bytes > 1024 * 1024)
    return false;
  HRESULT init = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  bool uninit = SUCCEEDED(init);
  bool ok = false;
  {
    ComPtr<IWICImagingFactory> factory;
    ComPtr<IWICBitmapDecoder> decoder;
    ComPtr<IWICBitmapFrameDecode> frame;
    ComPtr<IWICBitmapScaler> scale;
    ComPtr<IWICFormatConverter> convert;
    UINT w = 0, h = 0;
    if (SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr,
                                   CLSCTX_INPROC_SERVER,
                                   IID_PPV_ARGS(&factory))) &&
        SUCCEEDED(factory->CreateDecoderFromFilename(
            p.c_str(), nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand,
            &decoder)) &&
        SUCCEEDED(decoder->GetFrame(0, &frame)) &&
        SUCCEEDED(frame->GetSize(&w, &h)) && w && h && w <= 512 && h <= 512 &&
        SUCCEEDED(factory->CreateBitmapScaler(&scale)) &&
        SUCCEEDED(scale->Initialize(frame.Get(), 64, 64,
                                    WICBitmapInterpolationModeFant)) &&
        SUCCEEDED(factory->CreateFormatConverter(&convert)) &&
        SUCCEEDED(convert->Initialize(scale.Get(), GUID_WICPixelFormat32bppBGRA,
                                      WICBitmapDitherTypeNone, nullptr, 0,
                                      WICBitmapPaletteTypeCustom))) {
      std::array<unsigned char, 64 * 64 * 4> buf{};
      if (SUCCEEDED(convert->CopyPixels(nullptr, 64 * 4, (UINT)buf.size(),
                                        buf.data()))) {
        for (int y = 0; y < 64; y++)
          for (int x = 0; x < 64; x++) {
            auto *q = &buf[(y * 64 + x) * 4];
            pixel(x + 16, y + 16, q[2], q[1], q[0], q[3]);
          }
        ok = true;
      }
    }
  }
  if (uninit)
    CoUninitialize();
  return ok;
}
void compose(const Event &e, const std::string &path, const std::string &lang) {
  image.fill(0);
  for (int y = 0; y < H; y++)
    for (int x = 0; x < W; x++) {
      float dx = std::max({7.5f - x, x - (W - 8.5f), 0.f}),
            dy = std::max({7.5f - y, y - (H - 8.5f), 0.f});
      float distance = std::sqrt(dx * dx + dy * dy);
      if (distance > 8.5f)
        continue;
      unsigned a = (unsigned)(std::clamp(8.5f - distance, 0.f, 1.f) * 239);
      unsigned shade = unsigned(87 - 29.f * y / H);
      bool border =
          x == 0 || y == 0 || x == W - 1 || y == H - 1 || distance > 6.8f;
      pixel(x, y, border ? 139 : shade, border ? 141 : shade,
            border ? 143 : shade + 1, a);
    }
  for (int y = 14; y < 82; y++)
    for (int x = 14; x < 82; x++)
      pixel(x, y, 20, 22, 24, 70);
  if (!icon(path, e.id))
    cup(18, 18, 60, e.id);
  std::wstring earned = lang == "en"   ? L"You have earned a trophy."
                        : lang == "fr" ? L"Vous avez gagné un trophée."
                        : lang == "pt" ? L"Você ganhou um troféu."
                                       : L"Has ganado un trofeo.";
  text(earned, 96, 17, 279, 29, 17);
  cup(94, 49, 23, e.id);
  text(wide(e.name), 122, 46, 251, 30, 17);
}
} // namespace
extern "C" void tj_trophy_popup_configure(const char *path, const char *lang) {
  std::array<std::string, 13> names{};
  if (path) {
    std::error_code ec;
    auto p = std::filesystem::path(wide(path));
    auto size = std::filesystem::file_size(p, ec);
    if (!ec && size >= 12 && size <= 1024 * 1024) {
      std::ifstream f(p, std::ios::binary);
      std::vector<unsigned char> b((size_t)size);
      if (f.read((char *)b.data(), b.size())) {
        size_t pos = 8;
        bool good = memcmp(b.data(), "LJTRP01\0", 8) == 0;
        auto u = [&]() {
          if (pos + 4 > b.size()) {
            good = false;
            return uint32_t(0);
          }
          uint32_t v = uint32_t(b[pos]) << 24 | uint32_t(b[pos + 1]) << 16 |
                       uint32_t(b[pos + 2]) << 8 | b[pos + 3];
          pos += 4;
          return v;
        };
        auto str = [&](size_t max) {
          auto n = u();
          if (n > max || n > b.size() - pos) {
            good = false;
            return std::string();
          }
          std::string v((char *)b.data() + pos, n);
          pos += n;
          return v;
        };
        auto count = u();
        if (count != 13)
          good = false;
        auto comm = str(128);
        str(1024);
        str(4096);
        if (comm != "NPWR01344_00")
          good = false;
        uint32_t ids = 0;
        for (unsigned i = 0; i < 13 && good; i++) {
          auto id = u();
          u();
          u();
          u();
          auto name = str(512);
          str(4096);
          str(128);
          if (id >= 13 || (ids & (1u << id)))
            good = false;
          else {
            ids |= 1u << id;
            names[id] = std::move(name);
          }
        }
        if (!good || pos != b.size())
          names = {};
      }
    }
  }
  std::lock_guard lock(mutex);
  catalog = path ? path : "";
  language = lang ? lang : "es";
  previewNames = std::move(names);
}
extern "C" void tj_trophy_popup_preview(uint32_t id) {
  if (id >= 13)
    return;
  std::lock_guard lock(mutex);
  if (queue.size() >= 13)
    return;
  queue.push_back(
      {id, previewNames[id].empty() ? "Trofeo" : previewNames[id], true});
}
extern "C" void tj_trophy_popup_notify(uint32_t id, const char *name,
                                       const char *) {
  if (id >= 13)
    return;
  std::lock_guard lock(mutex);
  if ((seen & (1u << id)) || queue.size() >= 13)
    return;
  seen |= 1u << id;
  queue.push_back(
      {id, name ? std::string(name, std::min<size_t>(strlen(name), 1024))
                : "Trofeo"});
}
extern "C" int tj_trophy_popup_render(void *bgra, unsigned pitch,
                                      unsigned width, unsigned height,
                                      uint64_t now) {
  if (!bgra || width < W || height < H || pitch < width * 4ull)
    return 0;
  now = std::max(now, last);
  last = now;
  if (showing && now - started >= 5000)
    showing = false;
  if (!showing) {
    Event next;
    std::string path, lang;
    {
      std::lock_guard lock(mutex);
      if (queue.empty())
        return 0;
      next = std::move(queue.front());
      queue.pop_front();
      path = catalog;
      lang = language;
    }
    active = std::move(next);
    started = now;
    showing = true;
    compose(active, path, lang);
  }
  uint64_t elapsed = now - started;
  unsigned fade = elapsed < 200 && !active.preview
                      ? (unsigned)(elapsed * 255 / 200)
                  : elapsed > 4800 ? (unsigned)((5000 - elapsed) * 255 / 200)
                                   : 255;
  for (unsigned y = 0; y < H; y++) {
    auto *d = (unsigned char *)bgra + y * pitch;
    auto *s = image.data() + y * W * 4;
    for (unsigned x = 0; x < W * 4; x++)
      d[x] = (s[x] * fade + 127) / 255;
  }
  return 1;
}
