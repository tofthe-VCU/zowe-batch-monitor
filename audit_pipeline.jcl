//ZXXXXXJ  JOB (ACCT),'COBOL AUDIT',CLASS=A,MSGCLASS=X,
//             MSGLEVEL=(1,1),NOTIFY=&SYSUID
//* =========================================================
//* STEP 1: COMPILE, LINK, AND EXECUTE COBOL INSTREAM
//* =========================================================
//STEP1    EXEC IGYWCLG
//COBOL.SYSIN DD *
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SECAUDIT.
       
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT LOG-FILE ASSIGN TO LOGFILE
               ORGANIZATION IS SEQUENTIAL.
           SELECT RPT-FILE ASSIGN TO RPTFILE
               ORGANIZATION IS SEQUENTIAL.
               
       DATA DIVISION.
       FILE SECTION.
       FD  LOG-FILE
           RECORD CONTAINS 80 CHARACTERS.
       01  LOG-RECORD.
           05  LOG-USER      PIC X(8).
           05  FILLER        PIC X(1).
           05  LOG-IP        PIC X(15).
           05  FILLER        PIC X(1).
           05  LOG-STATUS    PIC X(10).
           05  FILLER        PIC X(45).
           
       FD  RPT-FILE
           RECORD CONTAINS 50 CHARACTERS.
       01  RPT-RECORD        PIC X(50).
       
       WORKING-STORAGE SECTION.
       01  WS-EOF-SWITCH     PIC X(1) VALUE 'N'.
       01  WS-TOTAL-READ     PIC 9(3) VALUE 0.
       01  WS-TOTAL-FLAGS    PIC 9(3) VALUE 0.
       
       01  WS-DETAIL-LINE.
           05  FILLER        PIC X(9) VALUE 'ALERT -> '.
           05  WS-RPT-USER   PIC X(8).
           05  FILLER        PIC X(5) VALUE ' IP: '.
           05  WS-RPT-IP     PIC X(15).
           
       01  WS-SUMMARY-LINE.
           05  FILLER        PIC X(16) VALUE 'TOTAL FLAGGED:  '.
           05  WS-SUM-FLAGS  PIC 9(3).
           
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT LOG-FILE
           OPEN OUTPUT RPT-FILE
           
           PERFORM 1000-READ-LOG UNTIL WS-EOF-SWITCH = 'Y'
           
           MOVE WS-TOTAL-FLAGS TO WS-SUM-FLAGS
           WRITE RPT-RECORD FROM WS-SUMMARY-LINE
           
           CLOSE LOG-FILE
           CLOSE RPT-FILE
           STOP RUN.
           
       1000-READ-LOG.
           READ LOG-FILE
               AT END
                   MOVE 'Y' TO WS-EOF-SWITCH
               NOT AT END
                   ADD 1 TO WS-TOTAL-READ
                   IF LOG-STATUS(1:6) = 'FAILED'
                       PERFORM 2000-FLAG-RECORD
                   END-IF
           END-READ.
           
       2000-FLAG-RECORD.
           ADD 1 TO WS-TOTAL-FLAGS
           MOVE LOG-USER TO WS-RPT-USER
           MOVE LOG-IP TO WS-RPT-IP
           WRITE RPT-RECORD FROM WS-DETAIL-LINE.
/*
//* =========================================================
//* STEP 2: PROVIDE DUMMY LOG DATA AND ROUTE OUTPUT
//* =========================================================
//GO.LOGFILE DD *
SYSADMIN 192.168.1.10    SUCCESS   
DEVUSER1 10.0.0.5        FAILED    
DBAUSER  172.16.0.4      SUCCESS   
UNKNOWN  10.0.0.99       FAILED    
/*
//GO.RPTFILE DD SYSOUT=*
//