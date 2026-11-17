// SPDX-License-Identifier: MIT
// Read-only original trophy browser. Author: matymeatboy.
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
void tj_trophy_menu_configure(const char *catalog, const char *language);
void tj_trophy_menu_open(void);
void tj_trophy_menu_key(int vk, long lp);
int tj_trophy_menu_render(void *bgra, unsigned pitch, unsigned width,
                          unsigned height);
#ifdef __cplusplus
}
#endif
