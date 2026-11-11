#include <stdint.h>

typedef struct {
    int (*mac)(const uint8_t *msg, uint32_t len);
} oracle_if_t;

/* Deep frame: the one a dropped function pointer would hide. */
__attribute__((noinline)) int crypto_mac(const uint8_t *msg, uint32_t len)
{
    volatile uint8_t block[512];
    uint32_t acc = 0u;
    for (uint32_t i = 0; i < 512u; i++) { block[i] = msg[i % len]; acc += block[i]; }
    return (int)acc;
}

/* A function whose address is never stored anywhere: an annotation naming it must fail. */
__attribute__((noinline)) int unbound_target(int x)
{
    volatile int y = x * 3;
    return y;
}

const oracle_if_t g_oracle = { crypto_mac };
