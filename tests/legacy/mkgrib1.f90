!> Test helper: write GRIB1 records (via w3emc PUTGB) from a control file
!> and a raw native-endian float32 stream, so the legacy fbwndgfs.x can be
!> fed exactly the same decoded values that the Python port reads from GRIB2.
!>
!> usage: mkgrib1 <control.txt> <fields.raw> <out.grib1>
!>
!> control.txt:
!>   line 1 : im jm lat1 lon1 lat2 lon2 di dj      (millidegrees)
!>   line 2 : number of records
!>   then   : param leveltype level yy mm dd hh fhour decscale   (one per record)
program mkgrib1
  implicit none
  character(len=512) :: ctl, raw, out
  integer :: im, jm, lat1, lon1, lat2, lon2, di, dj, nrec, n, iret, kf
  integer :: kpds(200), kgds(200)
  integer :: ipar, ltyp, lev, yy, mm, dd, hh, fhr, dsc
  real(4), allocatable :: f(:)
  logical(1), allocatable :: lb(:)

  call get_command_argument(1, ctl)
  call get_command_argument(2, raw)
  call get_command_argument(3, out)
  open(10, file=trim(ctl), status='old', action='read')
  open(11, file=trim(raw), status='old', action='read', access='stream', form='unformatted')
  read(10, *) im, jm, lat1, lon1, lat2, lon2, di, dj
  read(10, *) nrec
  kf = im * jm
  allocate(f(kf), lb(kf))
  lb = .true.
  call baopenw(51, trim(out), iret)
  if (iret /= 0) stop 'baopenw failed'

  kgds = 0
  kgds(1) = 0          ! equidistant cylindrical
  kgds(2) = im
  kgds(3) = jm
  kgds(4) = lat1
  kgds(5) = lon1
  kgds(6) = 128
  kgds(7) = lat2
  kgds(8) = lon2
  kgds(9) = di
  kgds(10) = dj
  kgds(11) = 0
  kgds(19) = 0
  kgds(20) = 255

  do n = 1, nrec
     read(10, *) ipar, ltyp, lev, yy, mm, dd, hh, fhr, dsc
     read(11) f
     kpds = 0
     kpds(1) = 7        ! NCEP
     kpds(2) = 96       ! GFS
     kpds(3) = 255      ! grid defined by GDS
     kpds(4) = 128      ! GDS present, no bitmap
     kpds(5) = ipar
     kpds(6) = ltyp
     kpds(7) = lev
     kpds(8) = yy       ! year of century
     kpds(9) = mm
     kpds(10) = dd
     kpds(11) = hh
     kpds(12) = 0
     kpds(13) = 1       ! hours
     kpds(14) = fhr
     kpds(15) = 0
     kpds(16) = 0
     kpds(17) = 0
     kpds(18) = 1
     kpds(19) = 2
     kpds(20) = 0
     kpds(21) = 21
     kpds(22) = dsc
     kpds(23) = 0
     call putgb(51, kf, kpds, kgds, lb, f, iret)
     if (iret /= 0) then
        print *, 'putgb failed ', iret
        stop 1
     end if
  end do
  call baclose(51, iret)
end program mkgrib1
