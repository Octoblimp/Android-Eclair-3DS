#!/bin/bash
#
# Copyright (C) 2010 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

#
# This script imports new versions of Bouncy Castle (http://bouncycastle.org) into the
# Android source tree.  To run, (1) fetch the appropriate tarball from the Bouncy Castle repository,
# (2) check the checksum, and then (3) run:
#   ./import_bouncycastle.sh bcprov-jdk*-*.tar.gz
#
# IMPORTANT: See README.android for additional details.

# turn on exit on error as well as a warning when it happens
set -e
trap  "echo WARNING: Exiting on non-zero subprocess exit code" ERR;

function die() {
  declare -r message=$1

  echo $message
  exit 1
}

function usage() {
  declare -r message=$1

  if [ ! "$message" = "" ]; then
    echo $message
  fi
  echo "Usage:"
  echo "  ./import_bouncycastle.sh import </path/to/bcprov-jdk*-*.tar.gz>"
  echo "  ./import_bouncycastle.sh regenerate <patch/*.patch>"
  echo "  ./import_bouncycastle.sh generate <patch/*.patch> </path/to/bcprov-jdk*-*.tar.gz>"
  exit 1
}

function main() {
  if [ ! -d patches ]; then
    die "Bouncy Castle patch directory patches/ not found"
  fi

  if [ ! -f bouncycastle.version ]; then
    die "bouncycastle.version not found"
  fi

  source bouncycastle.version
  if [ "$BOUNCYCASTLE_JDK" == "" -o "$BOUNCYCASTLE_VERSION" == "" ]; then
    die "Invalid bouncycastle.version; see README.android for more information"
  fi

  BOUNCYCASTLE_DIR=bcprov-jdk$BOUNCYCASTLE_JDK-$BOUNCYCASTLE_VERSION
  BOUNCYCASTLE_DIR_ORIG=$BOUNCYCASTLE_DIR.orig

  if [ ! -f bouncycastle.config ]; then
    die "bouncycastle.config not found"
  fi

  source bouncycastle.config
  if [ "$UNNEEDED_SOURCES" == "" -o "$NEEDED_SOURCES" == "" ]; then
    die "Invalid bouncycastle.config; see README.android for more information"
  fi

  declare -r command=$1
  shift || usage "No command specified. Try import, regenerate, or generate."
  if [ "$command" = "import" ]; then
    declare -r tar=$1
    shift || usage "No tar file specified."
    import $tar
  elif [ "$command" = "regenerate" ]; then
    declare -r patch=$1
    shift || usage "No patch file specified."
    [ -d $BOUNCYCASTLE_DIR ] || usage "$BOUNCYCASTLE_DIR not found, did you mean to use generate?"
    [ -d $BOUNCYCASTLE_DIR_ORIG ] || usage "$BOUNCYCASTLE_DIR_ORIG not found, did you mean to use generate?"
    regenerate $patch
  elif [ "$command" = "generate" ]; then
    declare -r patch=$1
    shift || usage "No patch file specified."
    declare -r tar=$1
    shift || usage "No tar file specified."
    generate $patch $tar
  else
    usage "Unknown command specified $command. Try import, regenerate, or generate."
  fi
}

function import() {
  declare -r BOUNCYCASTLE_SOURCE=$1

  untar $BOUNCYCASTLE_SOURCE
  applypatches

  cd $BOUNCYCASTLE_DIR

  cp -f LICENSE.html ../NOTICE
  touch ../MODULE_LICENSE_BSD_LIKE

  cd ..

  rm -r src
  mkdir -p src/main/java/
  for i in $NEEDED_SOURCES; do
    echo "Updating $i"
    mv $BOUNCYCASTLE_DIR/$i src/main/java/
  done

  # if [ $BOUNCYCASTLE_VERSION -ge 145 ]; then
  #   # move test directories from src/main/java to src/test/java
  #   for from in `find src/main/java -name test`; do
  #     to=`dirname $from | sed s,src/main/java/,src/test/java/,`
  #     echo "Moving $from to $to"
  #     mkdir -p $to
  #     mv $from $to
  #   done
  # fi

  # # move stray test files from src/main/java to src/test/java
  # if [ $BOUNCYCASTLE_VERSION -ge 137 ]; then
  #   mkdir -p src/test/java/org/bouncycastle/util/
  #   echo "Moving src/main/java/org/bouncycastle/util tests"
  #   mv src/main/java/org/bouncycastle/util/*Test*.java src/test/java/org/bouncycastle/util/
  # fi

  cleantar
}

function regenerate() {
  declare -r patch=$1

  generatepatch $patch
}

function generate() {
  declare -r patch=$1
  declare -r BOUNCYCASTLE_SOURCE=$2

  untar $BOUNCYCASTLE_SOURCE
  applypatches

  # # restore stray test files from src/test/java back to src/main/java
  # if [ $BOUNCYCASTLE_VERSION -ge 137 ]; then
  #   echo "Restoring src/test/java/org/bouncycastle/util"
  #   mv src/test/java/org/bouncycastle/util/* src/main/java/org/bouncycastle/util/
  # fi

  # # restore test directories from src/test/java back to src/main/java
  # if [ $BOUNCYCASTLE_VERSION -ge 145 ]; then
  #   for from in `find src/test/java -name test`; do
  #     to=`dirname $from | sed s,src/test/java/,src/main/java/,`
  #     echo "Restoring $from to $to"
  #     mkdir -p $to
  #     mv $from $to
  #   done
  # fi

  for i in $NEEDED_SOURCES; do
    echo "Restoring $i"
    rm -r $BOUNCYCASTLE_DIR/$i
    cp -rf src/main/java/$i $BOUNCYCASTLE_DIR/$i
  done

  generatepatch $patch
  cleantar
}

function untar() {
  declare -r BOUNCYCASTLE_SOURCE=$1

  # Remove old source
  cleantar

  # Process new source
  tar -zxf $BOUNCYCASTLE_SOURCE
  mv $BOUNCYCASTLE_DIR $BOUNCYCASTLE_DIR_ORIG
  find $BOUNCYCASTLE_DIR_ORIG -type f -print0 | xargs -0 chmod a-w
  (cd $BOUNCYCASTLE_DIR_ORIG && unzip -q src.zip)
  tar -zxf $BOUNCYCASTLE_SOURCE
  (cd $BOUNCYCASTLE_DIR && unzip -q src.zip)

  # Prune unnecessary sources
  echo "Removing $UNNEEDED_SOURCES"
  (cd $BOUNCYCASTLE_DIR_ORIG && rm -rf $UNNEEDED_SOURCES)
  (cd $BOUNCYCASTLE_DIR      && rm -r  $UNNEEDED_SOURCES)
}

function cleantar() {
  rm -rf $BOUNCYCASTLE_DIR_ORIG
  rm -rf $BOUNCYCASTLE_DIR
}

function applypatches () {
  cd $BOUNCYCASTLE_DIR

  # Apply appropriate patches
  for i in $BOUNCYCASTLE_PATCHES; do
    echo "Applying patch $i"
    patch -p1 < ../patches/$i || die "Could not apply patches/$i. Fix source and run: $0 regenerate patches/$i"

    # make sure no UNNEEDED_SOURCES got into the patch
    problem=0
    for s in $UNNEEDED_SOURCES; do
      if [ -e $s ]; then
        echo Unneeded source $s restored by patch $i
        problem=1
      fi
    done
    if [ $problem = 1 ]; then
      exit 1
    fi
  done

  # Cleanup patch output
  find . -type f -name "*.orig" -print0 | xargs -0 rm -f

  cd ..
}

function generatepatch() {
  declare -r patch=$1

  # Cleanup stray files before generating patch
  find $BOUNCYCASTLE_DIR -type f -name "*.orig" -print0 | xargs -0 rm -f
  find $BOUNCYCASTLE_DIR -type f -name "*~" -print0 | xargs -0 rm -f

  rm -f $patch
  LC_ALL=C TZ=UTC0 diff -Naur $BOUNCYCASTLE_DIR_ORIG $BOUNCYCASTLE_DIR >> $patch && die "ERROR: No diff for patch $path in file $i"
  echo "Generated patch $patch"
}

main $@
