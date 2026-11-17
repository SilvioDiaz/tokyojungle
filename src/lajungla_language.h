/* Game language selection. Author: matymeatboy.
 * IDs follow cellSysutil.h; restart the game after changing the launcher.
 * This USA dump carries EN, SU, FC and PU resources.
 */
#pragma once
#include <string.h>

static inline int lajungla_system_language(const char* language)
{
    if (!language || !*language || strcmp(language, "es") == 0) return 3;
    if (strcmp(language, "fr") == 0) return 2;
    if (strcmp(language, "pt") == 0) return 17;
    return 1;
}
