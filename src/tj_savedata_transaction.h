/* Save-directory transactions. Author: matymeatboy. */
#pragma once
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
int tj_savedata_transaction_begin(const char* original_directory, int is_save);
int tj_savedata_transaction_route(char* path, size_t capacity);
int tj_savedata_transaction_finish(int success);
int tj_savedata_transaction_delete(const char* original_directory);
int tj_savedata_transaction_recover_root(const char* savedata_root);
#ifdef __cplusplus
}
#endif
