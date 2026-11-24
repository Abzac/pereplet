Synthetic CBR regression fixtures, with no user books or copyrighted artwork.

`solid-rar5.cbr` contains three generated 40×60 PNGs (transparent, red, blue) and
ComicInfo.xml with test metadata. It was created with the existing local RAR
7.13 command line utility using `a -cfg- -ep -ma5 -s`.

`encrypted-headers.cbr` and `encrypted-file.cbr` contain the generated transparent
PNG and test rejection of `-hp` and `-p` archives respectively. Their password is
the public fixture string `cbr-test-password`.

Running tests does not require RAR/WinRAR/7-Zip. The application uses the single
official UnRAR DLL under `vendor/unrar`. RAR4 stored fixtures are constructed
directly by the tests so paths and size headers can be varied safely.
