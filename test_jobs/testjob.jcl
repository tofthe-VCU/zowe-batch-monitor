//TESTJOB  JOB (ACCT),'PIPELINE TEST',CLASS=A,MSGCLASS=X,
//             MSGLEVEL=(1,1),NOTIFY=&SYSUID
//* =========================================================
//* DUMMY JOB TO TEST CONCURRENT PIPELINE ROUTING
//* =========================================================
//STEP1    EXEC PGM=IEFBR14
//