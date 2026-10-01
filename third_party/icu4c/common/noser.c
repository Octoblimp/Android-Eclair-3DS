
#include "noser.h"

#include <stdio.h>

int daylight = 0;
int timezone = 0;

static int initted = 0;

void init(void)
{
    daylight = 1;
    timezone = 1;

    return;
}

size_t __ctype_get_mb_cur_max (void)
{
    return (size_t) sizeof(wchar_t);
}

/*
 * mbstowcs()
 *
 * convert multibyte string to wide character string.
 *
 * DESCRIPTION
 * The mbstowcs() function converts the multibyte string
 * addressed by s into the corresponding UNICODE string.
 * It stores up to n wide characters in pwcs. It stops
 * conversion after encountering and storing a null character. 
 *
 * PARAMETERS
 * pwcs:     Is the address of an array of wide characters,
 *           type wchar_t, to receive the UNICODE equivalent
 *           of multibyte string s.
 *    s:     Points to a null-terminated multibyte string
 *           to be converted to UNICODE.
 *    n:     Is the maximum number of characters to convert
 *           and store in pwcs.
 *
 * RETURN VALUES
 *           If successful, mbstowcs() returns the number of
 *           multibyte characters it converted, not including
 *           the terminating null character. If s is a null
 *           pointer or points to a null character, mbstowcs()
 *           returns zero. If mbstowcs() encounters an invalid
 *           multibyte sequence, it returns -1. 
 */
size_t mbstowcs(wchar_t *pwcs, const char *s, size_t n)
{
    size_t len = 0;

printf("IM IN MBSTOWCS\n");
    if(initted == 0)
    {
        init();
    }

    if(pwcs == NULL || s == NULL || n == 0)
    {
        return 0;
    }

    return len;
}

/*
 * wcstombs()
 *
 * convert wide character string to multibyte string 
 *
 * DESCRIPTION
 * The wcstombs() function converts a sequence of codes that
 * correspond to multibyte characters from the array pointed
 * to by pwcs into a sequence of multibyte characters that
 * begins in the initial shift state. Then, wcstombs() stores
 * these multibyte characters into the array pointed to by s.
 * If a multibyte character exceeds the limit of n total bytes
 * or if a NULL character is stored, wcstombs() stops. Each
 * code is converted as if by a call to the wctomb() function,
 * except that the shift state of the wctomb() function is not
 * affected.
 * No more than n bytes are modified in the array pointed to
 * by s. If copying takes place between objects that overlap,
 * the behavior is undefined. 
 *
 *
 * PARAMETERS
 *      s: Points to the sequence of multibyte characters.
 *   pwcs: Points to the sequence of wide characters.
 *      n: Is the maximum number of bytes that can be stored
 *         in the multibyte string.
 *
 * RETURN VALUES
 *      The wcstombs() function returns the number of bytes written
 *      into s, excluding the terminating NULL, if it was able to
 *      convert the wide character string. If the pwcs string is
 *      NULL, the wcstombs() function returns the required size of
 *      the destination string. If the conversion could not be
 *      performed, -1 is returned. 
 */
size_t wcstombs(char *s, const wchar_t *pwcs, size_t n)
{
    size_t len = 0;

    unsigned int effectiveLen = n - 1;
    unsigned int i            = 0;
printf("IM IN WCSTOMBS\n");
    if(s == NULL || pwcs == NULL ||  n == 0)
    {
        return 0;
    }

    if(initted == 0)
    {
        init();
    }

    i = strlen(s);

    len = (i <= effectiveLen) ? i : effectiveLen;

    for( ; i < len; ++i)
    {
        s[i] = (char) pwcs[i];
    }

    s[effectiveLen] = '\0';
    return len;
}
