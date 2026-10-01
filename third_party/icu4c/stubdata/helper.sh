#!/bin/bash
export TOOLS=$ANDROID_EABI_TOOLCHAIN/../../../icu-3.8
export WHICH=$1

if [ "$WHICH" == "" ]; then
    echo "Usage: ./helper <config name>"
    exit
fi;

if [ ! -d "cfg-$WHICH" ]; then
    echo "Configuration $WHICH does not exist."
    exit
fi;

cp cfg-$WHICH/icudt38l/res_index.txt icudt38l
cp cfg-$WHICH/icudt38l/brkitr/res_index.txt icudt38l/brkitr
cp cfg-$WHICH/icudt38l/coll/res_index.txt icudt38l/coll
cp cfg-$WHICH/icudt38l/rbnf/res_index.txt icudt38l/rbnf

echo "Compiling (possibly modified) source files into binaries..."
cd icudt38l
$TOOLS/gencnval convrtrs.txt
$TOOLS/genrb res_index.txt
cd ..

cd icudt38l/brkitr
$TOOLS/genrb res_index.txt
cd ../..

cd icudt38l/coll
$TOOLS/genrb res_index.txt
cd ../..

cd icudt38l/rbnf
$TOOLS/genrb res_index.txt
cd ../..

echo "Creating ICU data file..."
$TOOLS/icupkg -tl -s icudt38l -a cfg-$WHICH/icudt38l.txt new icudt38l.dat
cp icudt38l.dat icudt38l-$WHICH.dat
rm icudt38l.dat

echo "Finished."
