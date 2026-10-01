target remote localhost:1234
break __init_tls
commands
  printf "=== __init_tls entered, tls=%p thread=%p ===\n", $r0, $r1
  continue
end
break main
commands
  printf "=== main() entered ===\n"
  continue
end
break __set_errno
commands
  printf "=== __set_errno(%d) called, r0=$r0 ===\n", $r0
  print/x $r0
  continue
end
continue
bt
info registers r0 r1 r2 r3 pc lr
quit
