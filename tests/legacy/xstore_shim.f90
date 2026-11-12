!> Bounds-safe replacement for w3emc's XSTORE, used ONLY when building the
!> legacy reference executable for regression tests.
!>
!> WXAI19 (inside fbwndgfs.F) asks W3FI01 for the word length of a default
!> INTEGER (4 bytes), computes IWORDS = 1280/4 = 320 and calls XSTORE to blank
!> the 1280-byte bulletin block.  The XSTORE in libw3emc_d.a is compiled with
!> 8-byte default REALs, so it stores 320 * 8 = 2560 bytes and overruns the
!> block by 1280 bytes.  With gfortran the overrun lands on the SPACE output
!> buffer and wipes bulletin text that is waiting to be written.
!>
!> This shim stores MWORDS 4-byte words (what WXAI19 intended), so the block
!> is initialised without touching neighbouring memory.  fbwndgfs.F itself is
!> compiled unmodified.
subroutine xstore(cout, con, mwords)
  implicit none
  integer(4) :: cout(*)
  integer(8) :: con
  integer(8) :: mwords
  integer(8) :: i
  do i = 1, mwords
     cout(i) = int(con, 4)
  end do
end subroutine xstore
