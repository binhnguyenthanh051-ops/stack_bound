/* Test corpus for stack_bound slice 1. Built by tests/corpus/build.sh with MTB GCC 14.2.1
 * (Cortex-M4F, -O1 -g, -fstack-usage -fcallgraph-info=su). Each function exists to exercise one
 * behaviour; the frame sizes are whatever GCC makes of them, read back by the tests. */
#include <stdint.h>

typedef struct {
    int (*mac)(const uint8_t *msg, uint32_t len);
} oracle_if_t;

extern const oracle_if_t g_oracle;          /* crypto.c: bound to crypto_mac */
extern int helper_b(int x);                 /* util.c: calls util.c's own static helper */
extern int fact(int n);                     /* rec.c: recursive */
extern void asm_leaf(void);                 /* leaf.S: assembly, no .su */
extern int unbound_target(int x);           /* crypto.c: never address-taken */

volatile uint32_t g_sink;

uint32_t s_stack_a[256];                    /* 1024 B: task_a */
uint32_t s_stack_b[64];                     /*  256 B: task_b, deliberately small */

/* static, same name as util.c's helper but a different frame */
static __attribute__((noinline)) int helper(int x)
{
    volatile uint32_t buf[8];
    for (int i = 0; i < 8; i++) { buf[i] = (uint32_t)(x + i); }
    return (int)buf[x & 7];
}

__attribute__((noinline)) int verify(const uint8_t *m, uint32_t n)
{
    volatile uint8_t copy[16];
    for (uint32_t i = 0; i < 16u; i++) { copy[i] = m[i % n]; }
    return g_oracle.mac((const uint8_t *)copy, 16u);   /* indirect call */
}

void task_a(void *arg)
{
    (void)arg;
    uint8_t msg[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    for (;;) {
        g_sink = (uint32_t)verify(msg, 8u) + (uint32_t)helper((int)g_sink) + (uint32_t)helper_b(3);
    }
}

void task_b(void *arg)
{
    (void)arg;
    for (;;) {
        g_sink = (uint32_t)verify((const uint8_t *)"0123456789abcdef", 16u);
    }
}

void task_r(void *arg)                      /* recursion */
{
    (void)arg;
    for (;;) { g_sink = (uint32_t)fact((int)g_sink); }
}

void task_m(void *arg)                      /* calls assembly with no compiler frame */
{
    (void)arg;
    for (;;) { asm_leaf(); g_sink++; }
}

typedef void (*task_fn)(void *);
const task_fn g_tasks[] = { task_a, task_b, task_r, task_m };   /* keeps them linked */

void Reset_Handler(void)
{
    for (;;) {
        for (uint32_t i = 0; i < 4u; i++) { g_tasks[i]((void *)0); }
        g_sink = (uint32_t)unbound_target((int)g_sink);
    }
}
