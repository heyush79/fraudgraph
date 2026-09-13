# Build context is the REPO ROOT (see docker-compose.yml) so ../proto resolves for codegen.
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY proto ./proto
COPY stream-engine/pom.xml ./stream-engine/pom.xml
RUN mvn -q -B -f stream-engine/pom.xml dependency:go-offline
COPY stream-engine/src ./stream-engine/src
RUN mvn -q -B -f stream-engine/pom.xml -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /build/stream-engine/target/stream-engine-*.jar app.jar
EXPOSE 8081
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "app.jar"]
