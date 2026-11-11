#include <stdint.h>

/* Same name as tasks.c's static helper, different frame: identity must come from DWARF, not the name. */
static __attribute__((noinline)) int helper(int x)
{
    volatile uint32_t big[40];
    for (int i = 0; i < 40; i++) { big[i] = (uint32_t)(x * i); }
    return (int)big[(uint32_t)x % 40u];
}

__attribute__((noinline)) int helper_b(int x)
{
    return helper(x) + 1;
}
