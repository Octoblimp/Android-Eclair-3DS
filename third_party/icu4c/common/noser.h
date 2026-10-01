
#ifndef NOSER_H
#define NOSER_H

#include <stdlib.h>

size_t __ctype_get_mb_cur_max(void);
size_t mbstowcs(wchar_t *pwcs, const char *s, size_t n);
size_t wcstombs(char *s, const wchar_t *pwcs, size_t n);

#endif
