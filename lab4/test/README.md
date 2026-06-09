# Lab 4 


## Step 1 — Build the Container Images 

### 1.4 Loading the Images into Minikube

```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ minikube image ls | grep mzinga-webapp

docker.io/library/mzinga-webapp:2.0.0
docker.io/library/mzinga-webapp:1.0.0 
```



## Step 2 — Deploy the Initial Service (v1)


### 2.2 — Wait for Pods to Become Ready

``` 
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl rollout status deployment/webapp -n mzinga-lab4

deployment "webapp" successfully rolled out 
```

### 2.3 — Verify the Service

```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ Forwarding from 127.0.0.1:8080 -> 8080

Forwarding from [::1]:8080 -> 8080
Handling connection for 8080
```

``` 
(In second terminal)

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ curl -s http://localhost:8080

{"version": "1.0.0", "color": "blue", "hostname": "webapp-stable-847dfd7f56-45fzz", "message": "Hello from version 1.0.0"}

```



## Step 3 — In-Place Rolling Upgrade


### 3.1 — Start a Traffic Loop (Keep This Terminal Open)

```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ while true; do curl -s http://localhost:8080/ | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version'], d['hostname'])"; sleep 0.5; done

1.0.0 webapp-stable-847dfd7f56-45fzz
1.0.0 webapp-stable-847dfd7f56-45fzz
1.0.0 webapp-stable-847dfd7f56-45fzz
1.0.0 webapp-stable-847dfd7f56-45fzz
1.0.0 webapp-stable-847dfd7f56-45fzz
...
...

```


### 3.3 — Observe the Rollout


```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl get pods -n mzinga-lab4 -w

NAME                             READY   STATUS              RESTARTS      AGE
webapp-5f4f778774-42mld          1/1     Terminating         0             2m49s
webapp-5f4f778774-rfgnh          1/1     Terminating         0             2m56s
webapp-5f4f778774-zzfdb          1/1     Terminating         0             2m56s
webapp-76745bb6dd-6bk9b          1/1     Running             0             8s
webapp-76745bb6dd-9w6p6          1/1     Running             0             8s
webapp-76745bb6dd-sqlmv          0/1     ContainerCreating   0             1s
webapp-canary-7b6f5d58b9-75kmd   1/1     Running             1 (18m ago)   123m
webapp-canary-7b6f5d58b9-c748t   1/1     Running             1 (18m ago)   157m
webapp-canary-7b6f5d58b9-f22jf   1/1     Running             1 (18m ago)   158m
webapp-canary-7b6f5d58b9-n7pf9   1/1     Running             1 (18m ago)   123m
webapp-canary-7b6f5d58b9-rnw2r   1/1     Running             1 (18m ago)   159m
webapp-stable-847dfd7f56-45fzz   1/1     Running             1 (18m ago)   159m
webapp-stable-847dfd7f56-7jmdr   1/1     Running             1 (18m ago)   159m
webapp-stable-847dfd7f56-8dzxz   1/1     Running             1 (18m ago)   159m
webapp-stable-847dfd7f56-cp4n9   1/1     Running             1 (18m ago)   159m
webapp-stable-847dfd7f56-dxlhx   1/1     Running             1 (18m ago)   159m
webapp-76745bb6dd-sqlmv          0/1     Running             0             2s

```



### 3.4 — Verify Completion


```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ while true; do
  curl -s http://localhost:8080/ | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['version'], d['hostname'])
except Exception:
    pass
"
  sleep 0.5
done

2.0.0 webapp-76745bb6dd-sqlmv
2.0.0 webapp-76745bb6dd-sqlmv
1.0.0 webapp-stable-847dfd7f56-7jmdr
2.0.0 webapp-canary-7b6f5d58b9-f22jf
2.0.0 webapp-76745bb6dd-sqlmv
1.0.0 webapp-stable-847dfd7f56-cp4n9
2.0.0 webapp-canary-7b6f5d58b9-75kmd
1.0.0 webapp-stable-847dfd7f56-45fzz

```


## Step 4 — Recreate (Replace) Strategy


### 4.3 — Start a Traffic Loop

```

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ while true; do
  response=$(curl -s --max-time 1 http://localhost:8080/ 2>/dev/null)
  if [ -z "$response" ]; then
    echo "$(date +%H:%M:%S) [NO RESPONSE — service down]"
  else
    echo "$(date +%H:%M:%S) $(echo $response | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version'], d['hostname'])")"
  fi
  sleep 0.5
done


15:26:08 1.0.0 webapp-5f4f778774-g9dg9
15:26:08 1.0.0 webapp-5f4f778774-g9dg9
15:26:09 1.0.0 webapp-5f4f778774-g9dg9
15:26:10 1.0.0 webapp-5f4f778774-g9dg9
...
...

```


### 4.4 — Create the v2 Recreate Deployment and Observe the Downtime

**(Watching Pods)** 
``` 
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl get pods -n mzinga-lab4 -w

NAME                      READY   STATUS    RESTARTS   AGE
webapp-5f4f778774-4z27z   1/1     Running   0          4m8s
webapp-5f4f778774-g9dg9   1/1     Running   0          4m8s
webapp-5f4f778774-nbtwl   1/1     Running   0          4m8s

```

<br>

**(After Applying the v2 Deployment)**
```

webapp-5f4f778774-nbtwl   1/1     Terminating   0          4m14s
webapp-5f4f778774-g9dg9   1/1     Terminating   0          4m14s
webapp-5f4f778774-4z27z   1/1     Terminating   0          4m14s
webapp-5f4f778774-nbtwl   1/1     Terminating   0          4m14s
webapp-5f4f778774-4z27z   1/1     Terminating   0          4m14s
webapp-5f4f778774-g9dg9   1/1     Terminating   0          4m14s
webapp-5f4f778774-nbtwl   0/1     Error         0          4m44s
webapp-5f4f778774-4z27z   0/1     Error         0          4m44s
webapp-5f4f778774-g9dg9   0/1     Error         0          4m44s
webapp-76745bb6dd-7hn85   0/1     Pending       0          0s
webapp-76745bb6dd-rchlw   0/1     Pending       0          0s
webapp-76745bb6dd-7hn85   0/1     Pending       0          0s
webapp-76745bb6dd-4jt5k   0/1     Pending       0          0s
webapp-76745bb6dd-rchlw   0/1     Pending       0          0s
webapp-76745bb6dd-4jt5k   0/1     Pending       0          0s
webapp-76745bb6dd-7hn85   0/1     ContainerCreating   0          0s
webapp-76745bb6dd-4jt5k   0/1     ContainerCreating   0          0s
webapp-76745bb6dd-rchlw   0/1     ContainerCreating   0          0s
webapp-5f4f778774-g9dg9   0/1     Error               0          4m45s
webapp-5f4f778774-g9dg9   0/1     Error               0          4m45s
webapp-76745bb6dd-4jt5k   0/1     Running             0          1s
webapp-5f4f778774-nbtwl   0/1     Error               0          4m45s
webapp-5f4f778774-nbtwl   0/1     Error               0          4m45s
webapp-5f4f778774-nbtwl   0/1     Error               0          4m45s
webapp-5f4f778774-4z27z   0/1     Error               0          4m45s
webapp-76745bb6dd-7hn85   0/1     Running             0          1s
webapp-76745bb6dd-rchlw   0/1     Running             0          1s
webapp-5f4f778774-4z27z   0/1     Error               0          4m45s
webapp-5f4f778774-4z27z   0/1     Error               0          4m45s
webapp-76745bb6dd-7hn85   1/1     Running             0          6s
webapp-76745bb6dd-4jt5k   1/1     Running             0          7s
webapp-76745bb6dd-rchlw   1/1     Running             0          7s


```

<br>

**(Loop Terminal)**
```

15:27:08 1.0.0 webapp-5f4f778774-g9dg9
15:27:09 1.0.0 webapp-5f4f778774-g9dg9
15:27:09 1.0.0 webapp-5f4f778774-g9dg9
15:27:10 [NO RESPONSE — service down]
15:27:11 [NO RESPONSE — service down]
15:27:11 [NO RESPONSE — service down]
15:27:12 [NO RESPONSE — service down]
15:27:12 [NO RESPONSE — service down]
15:27:13 [NO RESPONSE — service down]
15:27:13 [NO RESPONSE — service down]
15:27:14 2.0.0 webapp-76745bb6dd-4jt5k
15:27:14 2.0.0 webapp-76745bb6dd-4jt5k
15:27:15 2.0.0 webapp-76745bb6dd-4jt5k
15:27:15 2.0.0 webapp-76745bb6dd-4jt5k
...
...

```



## Step 5 — Blue-Green Deployment 


### 5.5 — Switch Traffic to Green

```
...
15:40:59 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:40:59 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:00 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:00 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:01 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:01 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:02 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:41:02 2.0.0 webapp-green-6979594c4c-25j67
15:41:03 2.0.0 webapp-green-6979594c4c-25j67
15:41:03 2.0.0 webapp-green-6979594c4c-25j67
15:41:04 2.0.0 webapp-green-6979594c4c-25j67
15:41:04 2.0.0 webapp-green-6979594c4c-25j67
15:41:05 2.0.0 webapp-green-6979594c4c-25j67
15:41:05 2.0.0 webapp-green-6979594c4c-25j67
15:41:06 2.0.0 webapp-green-6979594c4c-25j67
...
...

```



### 5.6 — Instant Rollback

```
...
15:42:09 2.0.0 webapp-green-6979594c4c-25j67
15:42:09 2.0.0 webapp-green-6979594c4c-25j67
15:42:10 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:42:11 1.0.0 webapp-blue-546f6b7ffb-j7ktf
15:42:11 1.0.0 webapp-blue-546f6b7ffb-j7ktf
...
...

```


## Step 6 — Canary Release


### 6.3 — Verify the Traffic Split

```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ for i in $(seq 1 20); do curl -s http://localhost:8080/ | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"; done | sort | uniq -c

     19 1.0.0
     1  2.0.0
```


### 6.5 — Gradually Increase the Canary

**(canary to ~30%: 7 stable + 3 canary = 10 total)**
```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-stable --replicas=7 -n mzinga-lab4

deployment.apps/webapp-stable scaled

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-canary --replicas=3 -n mzinga-lab4
deployment.apps/webapp-canary scaled

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ for i in $(seq 1 20); do 
  response=$(curl -s http://localhost:8080/)
  if [ ! -z "$response" ]; then
    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"
  fi
  sleep 0.1
done | sort | uniq -c

     14 1.0.0
      4 2.0.0


```



**(Increase to ~50%)**
```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-stable --replicas=5 -n mzinga-lab4

deployment.apps/webapp-stable scaled

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-canary --replicas=5 -n mzinga-lab4

deployment.apps/webapp-canary scaled


shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ for i in $(seq 1 20); do 
  response=$(curl -s http://localhost:8080/)
  if [ ! -z "$response" ]; then
    echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])"
  fi
  sleep 0.1
done | sort | uniq -c
      
      8 1.0.0
     11 2.0.0
```

### 6.6 — Promote: Full Rollout to v2


```
shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-stable --replicas=0 -n mzinga-lab4

deployment.apps/webapp-stable scaled

shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ kubectl scale deployment/webapp-canary --replicas=10 -n mzinga-lab4

deployment.apps/webapp-canary scaled


shoya@VivoBook:~/Desktop/codes/AY-25-26-labs/mzinga/lab4-k8s$ for i in $(seq 1 20); do    
response=$(curl -s http://localhost:8080/)   
if [ ! -z "$response" ]; then     
echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin)['version'])";   fi   
sleep 0.1 
done | sort | uniq -c

     19 2.0.0
```
