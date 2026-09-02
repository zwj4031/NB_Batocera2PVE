#include <string.h>
#include <stdlib.h>

/* Minimal stub providing the NIS/libnsl symbols that tcp_wrappers (libwrap)
   and libasyncns reference. These are never exercised on a local streaming
   box, so returning safe defaults is sufficient for linking/loading. */

int yp_get_default_domain(char **dom) {
    if (dom) *dom = "local";
    return 0;
}
int yp_bind(const char *domain) { return 0; }
int yp_unbind(const char *domain) { return 0; }
int yp_match(const char *indomain, const char *inmap, const char *inkey, int inkeylen, char **outval, int *outvallen) { return 1; }
int yp_first(const char *indomain, const char *inmap, char **outkey, int *outkeylen, char **outval, int *outvallen) { return 1; }
int yp_next(const char *indomain, const char *inmap, const char *inkey, int inkeylen, char **outkey, int *outkeylen, char **outval, int *outvallen) { return 1; }
int yp_all(const char *indomain, const char *inmap, int (*cb)()) { return 1; }
int yp_order(const char *indomain, const char *inmap, int *outorder) { return 1; }
int yp_master(const char *indomain, const char *inmap, char **outname) { return 1; }
char *yperr_string(int code) { return (char*)""; }
char *ypprot_err(int code) { return (char*)""; }
int yp_update(char *a, char *b, unsigned c, char *d, int e, char *f, char *g) { return 1; }
