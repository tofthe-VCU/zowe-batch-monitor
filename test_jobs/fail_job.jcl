//INTFAIL  JOB (ACCT),'INTENTIONAL FAIL',CLASS=A,MSGCLASS=X,
//             MSGLEVEL=(1,1),NOTIFY=&SYSUID
//* Intentional failure for testing pipeline failure detection.
//STEP1    EXEC PGM=ZOWEFAIL
