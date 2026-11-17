// SPDX-License-Identifier: MIT
// Original implementation by matymeatboy. No firmware assets.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void tj_trophy_popup_configure(const char *catalog, const char *language);
void tj_trophy_popup_notify(uint32_t id, const char *name,
                            const char *description);
/* Diagnostic visual only: does not unlock, persist, or invoke the SDK. */
void tj_trophy_popup_preview(uint32_t id);
/* Writes a 384x96 premultiplied BGRA surface; call only on the render thread.
 */
int tj_trophy_popup_render(void *bgra, unsigned pitch, unsigned width,
                           unsigned height, uint64_t now_ms);
#ifdef __cplusplus
}
#endif
