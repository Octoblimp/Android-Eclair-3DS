This directory is used for building our Android
ICU data file. Unfortunately this requires some
manual tweaking, since the ICU build process is
not (yet) completely integrated into the Android
one. Fortunately it is supported by a script. :)

Quick tour:

- icudt38l/* contains the resources in unpacked
  form. It includes everything that comes with
  a vanilla ICU 3.8 as well as a couple of
  additional encodings required by Android.
  These are
  
  - gsm-03.38-2000.cnv
  - iso-8859_16-2001.cnv
  - docomo-shift_jis-2007.cnv
  - kddi-jisx-208-2007.cnv
  - kddi-shift_jis-2007.cnv
  - softbank-jisx-208-2007.cnv
  - softbank-shift_jis-2007.cnv

  Also, all character translation tables have
  been created with the "--small" option, so
  they use less space than in the vanilla ICU.

- Each of the cfg-* directories contains a
  different configuration for an ICU data file.
  Each of these configurations consists of a
  couple of files the directory structure of
  which mimics the structure in icudt38l/*.
  
  - icudt38l.txt contains the main manifest of
    our data file. It currently includes a lot
    of character conversion tables, locale data
    for various countries as well as timezone
    information.

  - Local manifest files named res_index.txt
    are residing in the following directories:
  
    - icudt38l
    - icudt38l/brkitr
    - icudt38l/coll
    - icudt38l/rbnf

    These also need to be updated to reflect
    any changes to the resources we want in
    Android.
  
- The actual data files are named using the
  same pattern, that is, icudt38l-<foo> is
  the data file geenrated from cfg-<foo>. The
  files currently need to be rebuilt manually
  whenever one of the manifests changes (don't
  forget to submit!). This can be conveniently
  done by running the ./helper.sh script as
  follows:
  
  ./helper foo
  
  Here, foo is the name of the configuration
  to build.
  
  Note: The script assumes you have done
  envsetup.sh and choosecombo before, because
  it relies on an enviroment variable pointing
  to the prebuilt tools. It also assumes the
  directory contents are writable, so as a
  Perforce user you might want to do a
  
  g4 edit ...
  
  before you run it.

- Currently we have these data files and
  configurations:
  
  - default .... what we had in Android 1.0
  - us-euro .... adds some Euro locales
  - us-japan ... adds full Japanese locale
                 and Docomo/KDDI/Softbank
		 support

  Note that very large data files are likely
  to break the prelink map. So this needs to
  be modified as well.
  
- The correct data file is chosen by the
  build depending on the PRODUCT_LOCALES
  variable. Note that is it possible you have
  to touch something in this directory for
  the build process to notice the changed
  selection.
