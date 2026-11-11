/* Assembly leaf: GCC writes no .su for it, so its frame must come from an annotation. */
    .syntax unified
    .thumb
    .text
    .global asm_leaf
    .type asm_leaf, %function
asm_leaf:
    push {r4, r5, lr}
    movs r4, #0
    pop  {r4, r5, pc}
    .size asm_leaf, .-asm_leaf
