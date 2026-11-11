/* Recursion: a cycle the walk must refuse without a depth annotation (MISRA C:2012 rule 17.2). */
__attribute__((noinline)) int fact(int n)
{
    volatile int keep = n;
    return (keep <= 1) ? 1 : keep * fact(keep - 1);
}
