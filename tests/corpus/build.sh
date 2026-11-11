#!/usr/bin/env bash
# Rebuild the test corpus: tests/corpus/out/{corpus.elf, corpus_nodebug.elf, *.su, *.ci}.
# Needs an arm-none-eabi GCC (MTB GCC 14.2.1 here). The outputs are committed, so the tests (and CI)
# never need a cross compiler; rerun this only when the corpus sources change.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
gcc_dir="${ARM_GCC_DIR:-C:/Infineon/Tools/mtb-gcc-arm-eabi/14.2.1/gcc/bin}"
cc="$gcc_dir/arm-none-eabi-gcc"
objcopy="$gcc_dir/arm-none-eabi-objcopy"
out="$here/out"
rm -rf "$out" && mkdir -p "$out"
cflags=(-mcpu=cortex-m4 -mthumb -mfloat-abi=hard -mfpu=fpv4-sp-d16 -O1 -g -ffreestanding
        -fno-builtin -fno-inline-small-functions -fstack-usage -fcallgraph-info=su)
cd "$out"
for f in tasks crypto util rec; do
  "$cc" "${cflags[@]}" -c "../src/$f.c" -o "$f.o"
done
"$cc" -mcpu=cortex-m4 -mthumb -c ../src/leaf.S -o leaf.o
"$cc" -mcpu=cortex-m4 -mthumb -nostdlib -nostartfiles -Wl,-e,Reset_Handler -Wl,--gc-sections \
      -Wl,-Ttext=0x10000000 tasks.o crypto.o util.o rec.o leaf.o -o corpus.elf
"$objcopy" --strip-debug corpus.elf corpus_nodebug.elf
"$objcopy" --strip-all corpus.elf corpus_stripped.elf
rm -f ./*.o
ls -1
